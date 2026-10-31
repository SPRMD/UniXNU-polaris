// Host fault-injection test. Executes the production command, window and block
// adapter code; IOKit ABI compatibility still requires the Darwin compile record.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <vector>
#include <algorithm>
using UInt64 = uint64_t;
using UInt32 = uint32_t;
using IOOptionBits = unsigned;
using IOReturn = int;
enum { kIOReturnSuccess, kIOReturnBadArgument, kIOReturnNotReady, kIOReturnBusy,
       kIOReturnIOError, kIOReturnTimeout, kIOReturnError, kIOReturnUnsupported,
       kIOReturnNotWritable, kIODirectionIn = 100, kIODirectionOut };
struct IOLock { bool held = false; };
static unsigned heldLocks;
static IOLock *IOLockAlloc () { return new IOLock; }
static void IOLockFree (IOLock *p) { assert (!p->held); delete p; }
static void IOLockLock (IOLock *p) { assert (!p->held); p->held = true; ++heldLocks; }
static void IOLockUnlock (IOLock *p) { assert (p->held); p->held = false; --heldLocks; }
static void *IOMalloc (size_t n) { return std::malloc (n); }
static void IOFree (void *p, size_t) { std::free (p); }
struct IOService {};
struct IOStorageAttributes {};
struct IOStorageCompletion {
  void *target;
  void (*action)(void *, void *, IOReturn, uint64_t);
  void *parameter;
};
struct IOMemoryDescriptor {
  std::vector<uint8_t> data;
  unsigned direction = kIODirectionIn;
  bool shortCopy = false;
  explicit IOMemoryDescriptor (size_t n) : data(n) {}
  uint64_t getLength () { return data.size (); }
  unsigned getDirection () { return direction; }
  uint64_t writeBytes (uint64_t at, const void *p, uint64_t n) {
    assert (heldLocks == 1); // window lock held, transport lock already released
    if (shortCopy) --n;
    assert (at + n <= data.size ());
    std::memcpy (data.data () + at, p, n);
    return n;
  }
};
#define OSDeclareDefaultStructors(name)
#define OSDefineMetaClassAndStructors(name, base)
struct IOBlockStorageDevice : IOService {
  virtual ~IOBlockStorageDevice () = default;
  virtual bool start (IOService *) { return true; }
  virtual void stop (IOService *) {}
  virtual void free () {}
  void setProperty (const char *, bool) {}
  void registerService () {}
  virtual IOReturn doEjectMedia () = 0;
  virtual IOReturn doFormatMedia (UInt64) = 0;
  virtual UInt32 doGetFormatCapacities (UInt64 *, UInt32) const = 0;
  virtual char *getVendorString () = 0;
  virtual char *getProductString () = 0;
  virtual char *getRevisionString () = 0;
  virtual char *getAdditionalDeviceInfoString () = 0;
  virtual IOReturn reportBlockSize (UInt64 *) = 0;
  virtual IOReturn reportMaxValidBlock (UInt64 *) = 0;
  virtual IOReturn reportEjectability (bool *) = 0;
  virtual IOReturn reportRemovability (bool *) = 0;
  virtual IOReturn reportWriteProtection (bool *) = 0;
  virtual IOReturn reportMediaState (bool *, bool *) = 0;
  virtual IOReturn doSynchronizeCache () = 0;
  virtual IOReturn doSynchronize (UInt64, UInt64, IOOptionBits) = 0;
  virtual IOReturn getWriteCacheState (bool *) = 0;
  virtual IOReturn setWriteCacheState (bool) = 0;
  virtual IOReturn doAsyncReadWrite (IOMemoryDescriptor *, UInt64, UInt64,
                                    IOStorageAttributes *, IOStorageCompletion *) = 0;
};
#include "RootTransportLayout.h"
#include "RootDiagnostics.h"
#include "TransferPoll.h"
#include "PolarisDmaHandoff.h"
static UfsRootDiagnostics gRootDiagnostic;
static uint8_t dma[kDmaBytes];
static IOLock transportLock;
static struct {
  uintptr_t hc = 0;
  uint8_t *virt = dma;
  uint64_t phys = 0x90000000;
  IOLock *lock = &transportLock;
  bool ready = true, poisoned = false;
} gHost;
static uint64_t ticks;
static uint32_t regs[64];
static unsigned rings;
enum class Mode { Good, Timeout, Fatal, BadTag, Residual, ScsiError };
static Mode mode;
static uint32_t read32 (uintptr_t, unsigned offset) { return regs[offset / 4]; }
static void cacheInvalidate (const void *, size_t) {}
static void cacheCivac (const void *, size_t) {}
static uint64_t mach_absolute_time () { return ticks; }
static void IODelay (unsigned) { ticks += 1000000; }
static constexpr unsigned kMicrosecondScale = 1;
static void clock_interval_to_deadline (uint32_t n, unsigned, uint64_t *d) { *d = ticks + n; }
static IOReturn recordTransport (IOReturn r, uint32_t) { return r; }
static void hostWrite (unsigned offset, uint32_t value) {
  if (offset == 0x20) { regs[offset / 4] &= ~value; return; }
  regs[offset / 4] = value;
  if (offset != 0x58) return;
  ++rings;
  if (mode == Mode::Timeout) return;
  if (mode == Mode::Fatal) { regs[0x20 / 4] = kUfsFatalStatus; return; }
  auto ucd = dma + kUcdOffset;
  auto rsp = ucd + kRspOffset;
  assert (ucd[0] == 1 && ucd[16] == 0x28); // reads only in adapter tests
  assert (ucd[1] == 0x40);
  uint64_t lba = (uint32_t(ucd[18]) << 24) | (uint32_t(ucd[19]) << 16) |
                 (uint32_t(ucd[20]) << 8) | ucd[21];
  unsigned blocks = (unsigned(ucd[23]) << 8) | ucd[24];
  for (unsigned i = 0; i < blocks; ++i)
    std::memset (dma + kDataOffset + i * 4096, (lba + i) & 255, 4096);
  rsp[0] = 0x21;
  rsp[3] = mode == Mode::BadTag ? 7 : 0;
  rsp[7] = mode == Mode::ScsiError ? 2 : 0;
  rsp[15] = mode == Mode::Residual ? 4 : 0;
  *reinterpret_cast<uint32_t *>(dma + 8) = 0;
  regs[0x58 / 4] = 0;
  regs[0x20 / 4] = 1;
}
#include "RootCommands.h"
#include "RootWindowRead.h"
#include "PolarisBlockDevice.h"
static void reset (Mode next = Mode::Good) {
  mode = next;
  std::memset (regs, 0, sizeof (regs));
  std::memset (dma, 0, sizeof (dma));
  gHost.poisoned = false;
  gHost.ready = true;
  rings = 0;
}
struct Done { unsigned calls = 0; IOReturn status = -1; uint64_t bytes = 0; };
static void complete (void *p, void *, IOReturn status, uint64_t bytes) {
  assert (!heldLocks);
  auto &d = *static_cast<Done *>(p);
  ++d.calls; d.status = status; d.bytes = bytes;
}
int main () {
  uint32_t smmu[1024] = {};
  smmu[0x20 / 4] = (1U << 27) | 2;
  smmu[0x800 / 4] = 0x800f0100;
  smmu[0xc00 / 4] = 1U << 16;
  auto read = [&](unsigned offset) { assert (offset < sizeof (smmu)); return smmu[offset / 4]; };
  assert (!polarisDmaHandoff (0x90000000, kDmaBytes, read));
  assert (polarisDmaHandoff (0xfffff000, kDmaBytes, read));
  smmu[0x800 / 4] = 0x80000100; // missing fifteen streams
  assert (polarisDmaHandoff (0x90000000, kDmaBytes, read));
  smmu[0x800 / 4] = 0x800f0100;
  smmu[0xc00 / 4] = 0; // translated mapping must not be assumed identity
  assert (polarisDmaHandoff (0x90000000, kDmaBytes, read));
  smmu[0xc00 / 4] = 1U << 16;
  smmu[0x804 / 4] = 0x80000101;
  assert (polarisDmaHandoff (0x90000000, kDmaBytes, read));
  smmu[0x804 / 4] = 0;
  smmu[0] = 8; // extended IDs unsupported
  assert (polarisDmaHandoff (0x90000000, kDmaBytes, read));
  uint8_t capacity[8] = {0, 0, 0, 99, 0, 0, 0x10, 0};
  uint64_t bytes = 0;
  assert (polarisCapacity (capacity, bytes) && bytes == 100 * 4096);
  capacity[6] = 2;
  assert (!polarisCapacity (capacity, bytes));
  capacity[6] = 0x10;
  std::memset (capacity, 255, 4);
  assert (!polarisCapacity (capacity, bytes));

  PolarisUfsBlock device;
  assert (device.configure (100 * 4096));
  assert (device.start (nullptr));
  UInt64 size, last;
  device.reportBlockSize (&size); device.reportMaxValidBlock (&last);
  assert (size == 4096 && last == 99);
  Done done;
  IOStorageCompletion completion = { &done, complete, nullptr };
  IOMemoryDescriptor buffer (40 * 4096);
  reset ();
  assert (device.doAsyncReadWrite (&buffer, 3, 40, nullptr, &completion) == 0);
  assert (done.calls == 1 && done.status == 0 && done.bytes == 40 * 4096 && rings == 2);
  for (unsigned i = 0; i < buffer.data.size (); ++i) assert (buffer.data[i] == 3 + i / 4096);
  buffer.direction = kIODirectionOut;
  assert (device.doAsyncReadWrite (&buffer, 3, 1, nullptr, &completion) == kIOReturnNotWritable);
  assert (rings == 2 && done.calls == 1);
  buffer.direction = kIODirectionIn;
  assert (device.doAsyncReadWrite (&buffer, 99, 2, nullptr, &completion) == kIOReturnBadArgument);
  assert (device.doAsyncReadWrite (&buffer, UINT64_MAX, 1, nullptr, &completion) == kIOReturnBadArgument);
  assert (device.doFormatMedia (0) == kIOReturnNotWritable);
  reset ();
  done = {};
  buffer.shortCopy = true;
  assert (!device.doAsyncReadWrite (&buffer, 0, 1, nullptr, &completion));
  assert (done.calls == 1 && done.status == kIOReturnIOError && done.bytes == 4095);
  buffer.shortCopy = false;
  for (Mode failure : {Mode::Timeout, Mode::Fatal, Mode::BadTag, Mode::Residual}) {
    reset (failure); done = {};
    assert (!device.doAsyncReadWrite (&buffer, 0, 1, nullptr, &completion));
    assert (done.calls == 1 && done.status != 0 && done.bytes == 0 && gHost.poisoned);
    auto before = rings;
    assert (!device.doAsyncReadWrite (&buffer, 0, 1, nullptr, &completion));
    assert (rings == before); // poisoned transport never resubmits DMA
  }
  reset ();
  uint32_t scsi;
  uint8_t writeCdb[10] = {0x2a};
  assert (hostScsiDir (0, writeCdb, 10, 1, 4096, 1000, &scsi) == kIOReturnBadArgument);
  assert (!rings);
  device.stop (nullptr); done = {};
  assert (!device.doAsyncReadWrite (&buffer, 0, 1, nullptr, &completion));
  assert (done.status == kIOReturnNotReady && !rings);
  device.free ();
  std::puts ("PASS: DMA handoff, capacity, block reads, bounds, writes, completion, stop, transport faults");
}
