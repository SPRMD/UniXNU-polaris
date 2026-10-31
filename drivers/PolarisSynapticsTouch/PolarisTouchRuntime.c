/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Polaris S3330/Synaptics RMI4 runtime transport.
 *
 * This is the small, board-specific transport that was used by the retired
 * Polaris XNU 8796 chain.  It is kept separate from the Darwin 23 IOKit
 * contract service so that the risky MMIO path is easy to audit and remains
 * opt-in.  The controller is on GPIO33/GPIO34 at address 0x20; GPIO99 is the
 * active-low reset line.  The code only runs after the caller supplies
 * polaris-touch-runtime=1 (or the historical polaristouchhid=1 argument).
 *
 * The transport publishes a bounded contact seqlock.  The Polaris HID sink can
 * subscribe with polaris_touch_runtime_set_sink(); no Android or Windows
 * binary is loaded here.  Every failure restores the two I2C pads and stops.
 */

#include <stdbool.h>
#include <stdint.h>

typedef unsigned long vm_offset_t;

extern vm_offset_t ml_io_map(vm_offset_t, unsigned long);
extern int PE_parse_boot_argn(const char *, void *, unsigned int);
extern int printf(const char *, ...);
extern void IOSleep(unsigned int);
extern void IODelay(unsigned int);
extern int kernel_thread_start(void (*)(void *, int), void *, void **);
extern void thread_deallocate(void *);

#define POLARIS_TOUCH_MAX_SLOTS 10u
#define POLARIS_TOUCH_FRAME_BYTES 8u

#define TLMM_NORTH_PA 0x03900000UL
#define SDA_CFG (33u * 0x1000u)
#define SCL_CFG (34u * 0x1000u)
#define RESET_CFG (99u * 0x1000u)
#define GPIO_IO 4u
#define I2C_ADDRESS 0x20u
#define CFG_MASK 0x3ffu
#define INPUT_PULL_UP (3u | (2u << 6))
#define OUTPUT_LOW ((2u << 6) | 0x200u)
#define GPIO_MAP_SIZE 0x23000UL
#define RESET_MAP_SIZE 0x1000UL

volatile uint32_t polaris_touch_runtime_state[8];
volatile uint32_t polaris_touch_seq;
volatile uint32_t polaris_touch_count;
volatile uint32_t polaris_touch_hid_reports;
volatile int polaris_touch_ids[POLARIS_TOUCH_MAX_SLOTS];
volatile int polaris_touch_x[POLARIS_TOUCH_MAX_SLOTS];
volatile int polaris_touch_y[POLARIS_TOUCH_MAX_SLOTS];

static void (*polaris_touch_sink)(void *);
static void *polaris_touch_sink_context;
static bool polaris_touch_started;
static unsigned polaris_touch_sink_busy;
static volatile uint32_t *gpio;
static volatile uint32_t *reset_gpio;
static uint32_t saved_sda_cfg;
static uint32_t saved_scl_cfg;
static uint32_t saved_sda_io;
static uint32_t saved_scl_io;
static bool contact_down[POLARIS_TOUCH_MAX_SLOTS];
static int contact_x[POLARIS_TOUCH_MAX_SLOTS];
static int contact_y[POLARIS_TOUCH_MAX_SLOTS];

/* Thread context only. The sink must only enqueue work, never wait for the
 * HID work loop or call set_sink recursively. Unregister drains any callback
 * before its owner can release the timer/work loop. */
static void
sink_lock(void)
{
	while (__atomic_exchange_n(&polaris_touch_sink_busy, 1u, __ATOMIC_ACQUIRE))
		IOSleep(1);
}

static void
sink_unlock(void)
{
	__atomic_store_n(&polaris_touch_sink_busy, 0u, __ATOMIC_RELEASE);
}

void
polaris_touch_runtime_set_sink(void (*sink)(void *), void *context)
{
	sink_lock();
	polaris_touch_sink_context = context;
	polaris_touch_sink = sink;
	/* Replay a frame published before HID registered, including all-up. */
	if (sink) sink(context);
	sink_unlock();
}

static void
notify_sink(void)
{
	sink_lock();
	if (polaris_touch_sink) polaris_touch_sink(polaris_touch_sink_context);
	sink_unlock();
}

static uint32_t
gpio_read(uint32_t offset)
{
	uint32_t value = gpio[offset / 4u];
	__asm__ volatile("dmb oshld" ::: "memory");
	return value;
}

static void
gpio_write(uint32_t offset, uint32_t value)
{
	__asm__ volatile("dmb oshst" ::: "memory");
	gpio[offset / 4u] = value;
	__asm__ volatile("dsb osh" ::: "memory");
}

static uint32_t
reset_read(uint32_t offset)
{
	uint32_t value = reset_gpio[offset / 4u];
	__asm__ volatile("dmb oshld" ::: "memory");
	return value;
}

static void
reset_write(uint32_t offset, uint32_t value)
{
	__asm__ volatile("dmb oshst" ::: "memory");
	reset_gpio[offset / 4u] = value;
	__asm__ volatile("dsb osh" ::: "memory");
}

/* Open-drain emulation: latch zero before enabling output and only drive low. */
static void
line_config(uint32_t config, bool release)
{
	uint32_t old = gpio_read(config);
	if (!release) {
		gpio_write(config + GPIO_IO, gpio_read(config + GPIO_IO) & ~2u);
	}
	gpio_write(config, (old & ~CFG_MASK) |
	    (release ? INPUT_PULL_UP : OUTPUT_LOW));
}

static bool
line_high(uint32_t config)
{
	return (gpio_read(config + GPIO_IO) & 1u) != 0;
}

static bool
clock_high(void)
{
	line_config(SCL_CFG, true);
	for (unsigned i = 0; i < 20; ++i) {
		if (line_high(SCL_CFG)) {
			IODelay(5);
			return true;
		}
		IODelay(5);
	}
	return false;
}

static void
bus_stop(void)
{
	line_config(SDA_CFG, false);
	IODelay(5);
	(void)clock_high();
	line_config(SDA_CFG, true);
	IODelay(5);
}

static bool
bus_idle(void)
{
	line_config(SDA_CFG, true);
	line_config(SCL_CFG, true);
	IODelay(20);
	return line_high(SDA_CFG) && line_high(SCL_CFG);
}

static bool
bus_start(bool repeated)
{
	line_config(SDA_CFG, true);
	if (!repeated) {
		if (!bus_idle()) return false;
	} else if (!clock_high()) {
		return false;
	}
	if (!line_high(SDA_CFG) || !line_high(SCL_CFG)) return false;
	line_config(SDA_CFG, false);
	IODelay(5);
	line_config(SCL_CFG, false);
	IODelay(5);
	return true;
}

static bool
write_byte(uint8_t value)
{
	for (int bit = 7; bit >= 0; --bit) {
		line_config(SDA_CFG, (value & (1u << bit)) != 0);
		IODelay(3);
		if (!clock_high()) return false;
		line_config(SCL_CFG, false);
		IODelay(3);
	}
	line_config(SDA_CFG, true);
	IODelay(5);
	if (!clock_high()) return false;
	bool ack = !line_high(SDA_CFG);
	line_config(SCL_CFG, false);
	IODelay(5);
	return ack;
}

static bool
read_byte(uint8_t *out, bool ack)
{
	if (out == 0) return false;
	uint8_t value = 0;
	line_config(SDA_CFG, true);
	for (unsigned bit = 0; bit < 8; ++bit) {
		if (!clock_high()) return false;
		value = (uint8_t)((value << 1) | (line_high(SDA_CFG) ? 1u : 0u));
		line_config(SCL_CFG, false);
		IODelay(3);
	}
	line_config(SDA_CFG, !ack);
	IODelay(3);
	if (!clock_high()) return false;
	line_config(SCL_CFG, false);
	line_config(SDA_CFG, true);
	*out = value;
	return true;
}

static bool
range_valid(uint16_t reg, unsigned length)
{
	unsigned low = reg & 0xffu;
	return length != 0 && length <= 96u && low < 0xffu &&
	    length <= 0xffu - low;
}

/* RMI4 page-select + repeated-start read, with bounded transfers. */
static bool
rmi_read(uint16_t reg, uint8_t *buffer, unsigned length)
{
	if (!buffer || !range_valid(reg, length)) return false;
	bool ok = false;
	if (!bus_start(false)) goto out;
	if (!write_byte((uint8_t)(I2C_ADDRESS << 1)) || !write_byte(0xff) ||
	    !write_byte((uint8_t)(reg >> 8))) goto out;
	bus_stop();
	if (!bus_start(false) || !write_byte((uint8_t)(I2C_ADDRESS << 1)) ||
	    !write_byte((uint8_t)reg) || !bus_start(true) ||
	    !write_byte((uint8_t)((I2C_ADDRESS << 1) | 1u))) goto out;
	for (unsigned i = 0; i < length; ++i) {
		if (!read_byte(&buffer[i], i + 1u < length)) goto out;
	}
	ok = true;
out:
	bus_stop();
	if (!bus_idle()) return false;
	return ok;
}

static void
publish_contacts(void)
{
	unsigned count = 0;
	__atomic_add_fetch(&polaris_touch_seq, 1u, __ATOMIC_SEQ_CST);
	__asm__ volatile("dmb ish" ::: "memory");
	for (unsigned slot = 0; slot < POLARIS_TOUCH_MAX_SLOTS; ++slot) {
		if (!contact_down[slot]) continue;
		__atomic_store_n(&polaris_touch_ids[count], (int)slot, __ATOMIC_RELAXED);
		__atomic_store_n(&polaris_touch_x[count], contact_x[slot], __ATOMIC_RELAXED);
		__atomic_store_n(&polaris_touch_y[count], contact_y[slot], __ATOMIC_RELAXED);
		if (++count == POLARIS_TOUCH_MAX_SLOTS) break;
	}
	__atomic_store_n(&polaris_touch_count, count, __ATOMIC_RELAXED);
	__asm__ volatile("dmb ish" ::: "memory");
	__atomic_add_fetch(&polaris_touch_seq, 1u, __ATOMIC_SEQ_CST);
	notify_sink();
}

static void
release_contacts(void)
{
	for (unsigned slot = 0; slot < POLARIS_TOUCH_MAX_SLOTS; ++slot) {
		contact_down[slot] = false;
	}
	publish_contacts();
}

static bool
decode_frame(const uint8_t *frame, int *x, int *y, bool *present)
{
	if (!frame || !x || !y || !present) return false;
	uint8_t status = frame[0] & 0x0fu;
	*present = false;
	if (status == 0) return true;
	if (status != 1) return false;
	*x = (int)((unsigned)frame[1] | ((unsigned)frame[2] << 8));
	*y = (int)((unsigned)frame[3] | ((unsigned)frame[4] << 8));
	if (*x < 0 || *x >= 1080 || *y < 0 || *y >= 2160) return false;
	*present = true;
	return true;
}

static bool
controller_probe(uint8_t f01[6], uint8_t f12[6])
{
	if (!rmi_read(0x00e3, f01, 6) || !rmi_read(0x00dd, f12, 6)) return false;
	/* F01/F12 PDT identity observed on the Polaris S3330 path. */
	if (f01[0] != 0x2c || f01[1] != 0x23 || f01[2] != 0x0c ||
	    f01[3] != 0x06 || f01[5] != 0x01) return false;
	if (f12[0] != 0x49 || f12[1] != 0x00 || f12[2] != 0x12 ||
	    f12[3] != 0x08 || f12[5] != 0x12) return false;
	return true;
}

static void
restore_pads(void)
{
	line_config(SDA_CFG, true);
	line_config(SCL_CFG, true);
	gpio_write(SDA_CFG + GPIO_IO, saved_sda_io);
	gpio_write(SCL_CFG + GPIO_IO, saved_scl_io);
	gpio_write(SDA_CFG, saved_sda_cfg);
	gpio_write(SCL_CFG, saved_scl_cfg);
}

static void
touch_thread(void *parameter, int wait_result)
{
	(void)parameter;
	(void)wait_result;
	uint8_t f01[6] = {0};
	uint8_t f12[6] = {0};
	uint8_t raw[POLARIS_TOUCH_MAX_SLOTS * POLARIS_TOUCH_FRAME_BYTES] = {0};
	unsigned slots = 1;
	unsigned consecutive_errors = 0;

	gpio = (volatile uint32_t *)ml_io_map(TLMM_NORTH_PA, GPIO_MAP_SIZE);
	reset_gpio = (volatile uint32_t *)ml_io_map(TLMM_NORTH_PA + RESET_CFG,
	    RESET_MAP_SIZE);
	if (!gpio || !reset_gpio) {
		printf("POLARIS TOUCH: TLMM map failed\n");
		return;
	}
	polaris_touch_runtime_state[0] = 1;
	saved_sda_cfg = gpio_read(SDA_CFG);
	saved_scl_cfg = gpio_read(SCL_CFG);
	saved_sda_io = gpio_read(SDA_CFG + GPIO_IO);
	saved_scl_io = gpio_read(SCL_CFG + GPIO_IO);

	/* Never pulse reset by default. Only release a line already held low. */
	unsigned reset_enabled = 0;
	(void)PE_parse_boot_argn("polaris-touch-reset", &reset_enabled,
	    sizeof(reset_enabled));
	if (reset_enabled == 1) {
		uint32_t cfg = reset_read(0);
		uint32_t io = reset_read(GPIO_IO);
		if ((cfg & CFG_MASK) != 0x201u || (io & 2u)) {
			printf("POLARIS TOUCH: reset line is not asserted; refusing release\n");
			return;
		}
		reset_write(GPIO_IO, io | 2u);
		IOSleep(200);
		if (!(reset_read(GPIO_IO) & 1u)) {
			printf("POLARIS TOUCH: reset did not rise\n");
			return;
		}
	}

	if (!bus_idle() || !controller_probe(f01, f12)) {
		printf("POLARIS TOUCH: RMI4 identity check failed\n");
		restore_pads();
		return;
	}
	polaris_touch_runtime_state[1] = 1;
	printf("POLARIS TOUCH: RMI4 F01/F12 accepted, data=0x%02x\n", f12[3]);

	/* Query5/Control23, when present, provides the slot count.  Refuse an
	 * unbounded value and retain the known-good single-slot fallback. */
	uint8_t query_size = 0;
	uint8_t query[32] = {0};
	if (rmi_read((uint16_t)(f12[0] + 4u), &query_size, 1) &&
	    query_size >= 4 && query_size <= sizeof(query) &&
	    rmi_read((uint16_t)(f12[0] + 5u), query, query_size)) {
		if (query[1 + 23 / 8] & (1u << (23 % 8))) {
			unsigned offset = 0;
			for (unsigned n = 0; n < 23; ++n)
				offset += (query[1 + n / 8] >> (n % 8)) & 1u;
			uint8_t ctrl[2] = {0};
			if (offset <= 0xffu - f12[2] &&
			    rmi_read((uint16_t)(f12[2] + offset), ctrl, 2) &&
			    (ctrl[0] & 1u) && ctrl[1] >= 1 && ctrl[1] <= POLARIS_TOUCH_MAX_SLOTS)
				slots = ctrl[1];
		}
	}
	polaris_touch_runtime_state[2] = slots;
	printf("POLARIS TOUCH: polling %u slot(s)\n", slots);

	for (;;) {
		bool valid = rmi_read(f12[3], raw, slots * POLARIS_TOUCH_FRAME_BYTES);
		bool changed = false;
		if (valid) {
			for (unsigned slot = 0; slot < slots; ++slot) {
				int x = 0, y = 0;
				bool present = false;
				if (!decode_frame(raw + slot * POLARIS_TOUCH_FRAME_BYTES,
				    &x, &y, &present)) {
					valid = false;
					break;
				}
				if (present != contact_down[slot] ||
				    (present && (x != contact_x[slot] || y != contact_y[slot]))) {
					changed = true;
				}
				contact_down[slot] = present;
				if (present) {
					contact_x[slot] = x;
					contact_y[slot] = y;
				}
			}
		}
		if (!valid) {
			polaris_touch_runtime_state[5]++;
			++consecutive_errors;
			release_contacts();
			if (consecutive_errors >= 8) {
				printf("POLARIS TOUCH: repeated invalid frames; stopping\n");
				break;
			}
		} else {
			consecutive_errors = 0;
			if (changed) {
				polaris_touch_runtime_state[3]++;
				publish_contacts();
			}
		}
		IOSleep(20);
	}
	release_contacts();
	restore_pads();
	printf("POLARIS TOUCH: stopped and pads restored\n");
}

int
polaris_touch_runtime_start(void)
{
	unsigned enabled = 0;
	if (PE_parse_boot_argn("polaris-touch-runtime", &enabled,
	    sizeof(enabled)) != 0 && enabled == 1) {
		/* explicit modern gate */
	} else if (PE_parse_boot_argn("polaristouchhid", &enabled,
	    sizeof(enabled)) == 0 || enabled != 1) {
		return 0;
	}
	if (__atomic_exchange_n(&polaris_touch_started, true, __ATOMIC_ACQ_REL)) return 1;
	void *thread = 0;
	int result = kernel_thread_start(touch_thread, 0, &thread);
	if (result == 0) {
		if (thread) thread_deallocate(thread);
		return 1;
	}
	__atomic_store_n(&polaris_touch_started, false, __ATOMIC_RELEASE);
	printf("POLARIS TOUCH: thread start failed %d\n", result);
	return 0;
}
