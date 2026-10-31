// SPDX-License-Identifier: BSD-2-Clause-Patent
// Adapted from UniXNU-judyln NativeUfsFull.cpp.txt's NativeUfsBlock.
// Included after the transport and window reader; no independent translation unit.
class PolarisUfsBlock : public IOBlockStorageDevice {
  OSDeclareDefaultStructors (PolarisUfsBlock)
  uint64_t bytes = 0;
  uint8_t *bounce = nullptr;
  IOLock *windowLock = nullptr;
  bool online = false;
public:
  bool configure (uint64_t capacity) {
    if (!ufsWindowGeometry (0, capacity) || (capacity & 4095)) return false;
    bytes = capacity;
    windowLock = IOLockAlloc ();
    bounce = static_cast<uint8_t *> (IOMalloc (kDataMax));
    return windowLock && bounce;
  }
  bool start (IOService *provider) override {
    if (!bounce || !windowLock || !IOBlockStorageDevice::start (provider)) return false;
    online = true;
    setProperty ("PolarisHardwareValidated", false);
    registerService ();
    return true;
  }
  void stop (IOService *provider) override {
    IOLockLock (windowLock);
    online = false;
    IOLockUnlock (windowLock);
    IOBlockStorageDevice::stop (provider);
  }
  void free () override {
    if (bounce) IOFree (bounce, kDataMax);
    if (windowLock) IOLockFree (windowLock);
    IOBlockStorageDevice::free ();
  }
  IOReturn doEjectMedia () override { return kIOReturnUnsupported; }
  IOReturn doFormatMedia (UInt64) override { return kIOReturnNotWritable; }
  UInt32 doGetFormatCapacities (UInt64 *, UInt32) const override { return 0; }
  char *getVendorString () override { return const_cast<char *> ("Polaris"); }
  char *getProductString () override { return const_cast<char *> ("UFS LUN 0"); }
  char *getRevisionString () override { return const_cast<char *> ("0.1"); }
  char *getAdditionalDeviceInfoString () override { return const_cast<char *> ("experimental read-only UFS"); }
  // Preserve the physical LUN's 4 KiB geometry: its GPT LBAs are NOT 512-byte LBAs.
  IOReturn reportBlockSize (UInt64 *v) override { *v = 4096; return kIOReturnSuccess; }
  IOReturn reportMaxValidBlock (UInt64 *v) override { *v = bytes / 4096 - 1; return kIOReturnSuccess; }
  IOReturn reportEjectability (bool *v) override { *v = false; return kIOReturnSuccess; }
  IOReturn reportRemovability (bool *v) override { *v = false; return kIOReturnSuccess; }
  IOReturn reportWriteProtection (bool *v) override { *v = true; return kIOReturnSuccess; }
  IOReturn reportMediaState (bool *present, bool *changed) override {
    IOLockLock (windowLock);
    *present = online;
    if (changed) *changed = false;
    IOLockUnlock (windowLock);
    return kIOReturnSuccess;
  }
  IOReturn doSynchronizeCache () override { return kIOReturnUnsupported; }
  IOReturn doSynchronize (UInt64, UInt64, IOOptionBits) override { return kIOReturnUnsupported; }
  IOReturn getWriteCacheState (bool *v) override { *v = false; return kIOReturnSuccess; }
  IOReturn setWriteCacheState (bool) override { return kIOReturnNotWritable; }
  IOReturn doAsyncReadWrite (IOMemoryDescriptor *buffer, UInt64 block, UInt64 count,
                            IOStorageAttributes *, IOStorageCompletion *completion) override {
    if (!buffer || !completion || !completion->action || !count || block >= bytes / 4096 ||
        count > bytes / 4096 - block || buffer->getLength () < count * 4096)
      return kIOReturnBadArgument;
    if (buffer->getDirection () != kIODirectionIn) return kIOReturnNotWritable;
    struct Operations {
      PolarisUfsBlock *device;
      IOMemoryDescriptor *buffer;
      void lock () { IOLockLock (device->windowLock); }
      void unlock () { IOLockUnlock (device->windowLock); }
      IOReturn read (uint64_t lba, uint32_t blocks, void *out) {
        return device->online ? hostRead4k (0, lba, blocks, out) : kIOReturnNotReady;
      }
      IOReturn verify (uint64_t, const void *, size_t) { return kIOReturnSuccess; }
      uint64_t copy (uint64_t offset, const void *data, uint64_t length) {
        return buffer->writeBytes (offset, data, length);
      }
    } ops = { this, buffer };
    UfsWindowResult result = ufsReadWindow (ops, 0, bytes, block * 8, count * 8, bounce);
    // Completion may re-enter the device; both window and transport locks are released.
    completion->action (completion->target, completion->parameter, result.status, result.done);
    return kIOReturnSuccess;
  }
};
OSDefineMetaClassAndStructors (PolarisUfsBlock, IOBlockStorageDevice)
