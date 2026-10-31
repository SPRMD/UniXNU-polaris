// SPDX-License-Identifier: BSD-2-Clause-Patent
// The touch screen for iOS: publishes PolarisHidInput on IOHIDResource, fed by
// the Polaris Synaptics RMI4 runtime.
// Adapted from the pinned iPadOS HID ABI reference.
// (08cde20): the same class registration and the same properties backboardd needs on the event service, without scripted
// Home presses.
//
// polaris-touch-hid=1 publishes the default combined device (keyboard collection first, then the touch screen; needs
// polaris-touch-hid=1, which PolarisHidInput reads): the in-kernel IOHIDEventDriver of this kernelcache has no digitizer
// personality (its rules: game-controller pointers 1/5 and 1/4, Peppy display 0xc/1, buttons 0xb/1, keyboards 1/6 and 1/7, a
// sensor 0xff0c/3), so a touch-only device is left to the DriverKit AppleUserHIDEventService, whose server is never launched
// on this board. The keyboard usage matches "HID Keyboard Driver", which also dispatches the device's digitizer collection.
// polaris-touch-hid=2 keeps the touch-only device.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSIterator.h>
#include <libkern/c++/OSKext.h>
#include <libkern/c++/OSBoolean.h>
#include <pexpert/pexpert.h>
#include <mach/kmod.h>

extern "C" kern_return_t kernel_thread_start(void (*)(void *, wait_result_t), void *, thread_t *);
extern "C" void thread_deallocate(thread_t);
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void polaris_hid_static_init(void) __asm__("__GLOBAL__sub_I_PolarisHidInput.cpp");
extern "C" IOService *polaris_hid_input_allocate(void);
extern "C" IOService *polaris_hid_touch_allocate(void);
static unsigned polaris_hid_mode;
extern "C" {
extern kern_return_t OSKextLoadKextWithIdentifier(const char *);
// [0] init [1] attach [2] started [3] tick [4] key report [5] key report [6] touch report [7] start failed (PolarisHidInput's events)
volatile uint32_t polaris_hid_input_events[8];
volatile int polaris_hid_input_results[8] = {-1, -1, -1, -1, -1, -1, -1, -1};
volatile uint32_t polaris_hid_stage;
volatile int polaris_hid_load_status = -1, polaris_hid_meta_status = -1;
volatile uint32_t polaris_hid_device_size;
// The class of the event driver that attached below the touch screen device (the live banner's TOUCH row).
char polaris_hid_driver[40];

// Hooks PolarisHidInput calls.
void polaris_hid_input_observed(unsigned event, int result) {
    if (event < 8) {
        polaris_hid_input_events[event] = polaris_hid_input_events[event] + 1;
        polaris_hid_input_results[event] = result;
    }
}
// The keyboard device's Home presses; this board publishes only the touch screen.
bool polaris_hid_input_requested(void) { return false; }
}

static IORegistryEntry *findEventDriver(IORegistryEntry *parent, unsigned depth) {
    if (!depth) return nullptr;
    OSIterator *it = parent->getChildIterator(gIOServicePlane);
    if (!it) return nullptr;
    IORegistryEntry *found = nullptr;
    while (OSObject *child = it->getNextObject()) {
        IORegistryEntry *entry = OSDynamicCast(IORegistryEntry, child);
        if (!entry) continue;
        if (entry->metaCast("IOHIDEventDriver")) { found = entry; break; }
        if ((found = findEventDriver(entry, depth - 1))) break;
    }
    it->release();
    return found;
}

// PolarisHidInput calls this once a second. backboardd classifies a digitizer by Built-In/DisplayIntegrated on the event service
// it opened and drops digitizer events unless that service has PrimaryUsagePage 0x0D and PrimaryUsage 4 (Touch Screen); publish
// them on the IOHIDEventDriver and its interface once (each setProperty is a registry change notification).
extern "C" __attribute__((noinline)) void polaris_hid_live_checkpoint(IOService *device) {
    static IORegistryEntry *publishedFor;
    IORegistryEntry *driver = findEventDriver(device, 4);
    if (!driver || publishedFor == driver || !device->getProperty("Built-In")) return;
    publishedFor = driver;
    strlcpy(polaris_hid_driver, driver->getMetaClass()->getClassName(), sizeof(polaris_hid_driver));
    driver->setProperty("Built-In", kOSBooleanTrue);
    driver->setProperty("DisplayIntegrated", kOSBooleanTrue);
    driver->setProperty("PrimaryUsagePage", (unsigned long long)0x0d, 32);
    driver->setProperty("PrimaryUsage", (unsigned long long)4, 32);
    if (IORegistryEntry *interface = driver->getParentEntry(gIOServicePlane)) {
        interface->setProperty("Built-In", kOSBooleanTrue);
        interface->setProperty("DisplayIntegrated", kOSBooleanTrue);
        interface->setProperty("PrimaryUsagePage", (unsigned long long)0x0d, 32);
        interface->setProperty("PrimaryUsage", (unsigned long long)4, 32);
    }
    IOLog("TOUCH hid event driver %s published as the built-in touch screen\n", driver->getMetaClass()->getClassName());
}

static void polaris_hid_thread(void *, wait_result_t) {
    polaris_hid_stage = 1;
    polaris_hid_load_status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOHIDFamily");
    if (polaris_hid_load_status == 0)
        OSKext::loadKextWithIdentifier("com.apple.iokit.IOHIDEventDriver", true, false, kOSKextExcludeNone, kOSKextExcludeNone,
            nullptr);
    const OSSymbol *name = OSSymbol::withCString("IOHIDDevice");
    const OSMetaClass *meta = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
    polaris_hid_device_size = meta ? meta->getClassSize() : 0;
    OSSafeReleaseNULL(name);
    polaris_hid_stage = 2;
    IOService *resource = nullptr;
    OSDictionary *match = IOService::serviceMatching("IOHIDResource");
    if (polaris_hid_load_status == 0 && match) resource = IOService::waitForMatchingService(match, 10000000000ULL);
    OSSafeReleaseNULL(match);
    // PolarisHidInput is compiled against the original 208-byte IOHIDDevice (scripts/data/hid-device-abi.json).
    if (!resource || polaris_hid_device_size != 208) {
        IOLog("TOUCH hid not started: IOHIDFamily load=%d IOHIDResource=%d IOHIDDevice size=%u\n", polaris_hid_load_status,
            resource != nullptr, polaris_hid_device_size);
        OSSafeReleaseNULL(resource);
        return;
    }
    polaris_hid_stage = 3;
    void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if (handle) {
        polaris_hid_static_init();
        polaris_hid_meta_status = OSMetaClass::postModLoad(handle);
    }
    bool started = false;
    if (handle && !polaris_hid_meta_status) {
        IOService *touch = polaris_hid_mode == 2 ? polaris_hid_touch_allocate() : polaris_hid_input_allocate();
        started = touch && touch->metaCast("IOHIDDevice") && touch->init() && touch->attach(resource) && touch->start(resource);
        if (!started && touch) {
            touch->detach(resource);
            OSSafeReleaseNULL(touch);
        }
        // The device lives for the boot: its registry attachment and work loop stay owned by IOKit.
    }
    polaris_hid_stage = started ? 4 : 5;
    IOLog("TOUCH hid %s device %s (metaclass status %d)\n", polaris_hid_mode == 2 ? "touch-only" : "keyboard+touch",
        started ? "started on IOHIDResource" : "FAILED to start", polaris_hid_meta_status);
    OSSafeReleaseNULL(resource);
}

// Called from the late display probe (package/LegacyDisplayProbe.cpp); polaris-touch-hid=1 (combined) or 2 (touch-only).
extern "C" void polaris_hid_touch_start(void) {
    unsigned enabled = 0;
    PE_parse_boot_argn("polaris-touch-hid", &enabled, sizeof(enabled));
    if ((enabled != 1 && enabled != 2) || polaris_hid_stage) return;
    polaris_hid_mode = enabled;
    thread_t thread = nullptr;
    if (kernel_thread_start(polaris_hid_thread, nullptr, &thread) == KERN_SUCCESS) thread_deallocate(thread);
}
