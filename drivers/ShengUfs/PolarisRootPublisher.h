// SPDX-License-Identifier: BSD-2-Clause-Patent
// Real IOBlockStorageDevice -> IOBlockStorageDriver -> IOMedia integration.
// As in ShengUfs/sirius, publication runs outside the provider's start path.
#include "RootPublication.h"
struct PolarisPendingWindows {
  IOService *owner;
  PolarisUfsBlock *device[2];
  bool attached[2];
  UfsRootPlan plan;
};

static void polarisDiscardWindow (PolarisPendingWindows &p, unsigned i) {
  if (!p.device[i]) return;
  if (p.attached[i]) p.device[i]->detach (p.owner);
  p.device[i]->release (); p.device[i] = nullptr; p.attached[i] = false;
}

static bool polarisWindowMediaReady (PolarisUfsBlock *device) {
  // No direct IOMedia vtable dependency: query actual IOMedia services and
  // require a whole, non-writable, correctly sized descendant of THIS window.
  // This does not confuse an unrelated disk with the same label/UUID for ours.
  OSDictionary *matching = IOService::serviceMatching ("IOMedia");
  OSIterator *iterator = matching ? IOService::getMatchingServices (matching) : nullptr;
  bool found = false;
  for (unsigned n = 0; iterator && iterator->isValid () && n < 256; ++n) {
    IORegistryEntry *media = OSDynamicCast (IORegistryEntry, iterator->getNextObject ());
    if (!media) break;
    OSNumber *size = OSDynamicCast (OSNumber, media->getProperty ("Size"));
    OSNumber *block = OSDynamicCast (OSNumber, media->getProperty ("Preferred Block Size"));
    if (media->getProperty ("Whole") != kOSBooleanTrue ||
        media->getProperty ("Writable") != kOSBooleanFalse || !size || !block ||
        size->unsigned64BitValue () != device->windowBytes () || block->unsigned32BitValue () != 512) continue;
    IORegistryIterator *parents = IORegistryIterator::iterateOver (
      media, gIOServicePlane, kIORegistryIterateRecursively | kIORegistryIterateParents);
    found = parents && ufsMediaHasAncestor (*parents, device);
    OSSafeReleaseNULL (parents);
    if (found) break;
  }
  OSSafeReleaseNULL (iterator);
  OSSafeReleaseNULL (matching);
  return found;
}

static void polarisPublishWindowsThread (void *argument, wait_result_t) {
  auto *pending = static_cast<PolarisPendingWindows *> (argument);
  struct Operations {
    PolarisPendingWindows &p;
    bool start (unsigned i) { return p.device[i]->start (p.owner); }
    bool wait (unsigned i) {
      for (unsigned n = 0; n < 300; ++n) {
        if (polarisWindowMediaReady (p.device[i])) return true;
        IOSleep (100);
      }
      return false;
    }
    void discard (unsigned i) { polarisDiscardWindow (p, i); }
  } ops = { *pending };
  UfsRootPublicationResult result = ufsPublishRootWindows (ops, pending->plan);
  pending->owner->setProperty ("PolarisUfsWindowMediaReady", result.phase == UfsRootPhase::Complete);
  IOLog ("POLARIS_UFS windows: phase=%u index=%u started=%u; APFS/root not qualified\n",
         unsigned (result.phase), result.index, result.published);
  // Started windows retain an owner reference for the boot: clients may have
  // asynchronous I/O even after the bounded media wait times out. Unstarted
  // windows have already been detached/released by the shared lifecycle helper.
  pending->owner->release ();
  IOFree (pending, sizeof (*pending));
}

static bool polarisPrepareWindows (IOService *owner, const PolarisRootLayout &layout, uint64_t lunBytes) {
  auto *pending = static_cast<PolarisPendingWindows *> (IOMalloc (sizeof (PolarisPendingWindows)));
  if (!pending) return false;
  bzero (pending, sizeof (*pending)); pending->owner = owner;
  const char *names[2] = { layout.window[0].name, layout.window[1].name };
  if (!ufsBuildRootPlan (names, 2, pending->plan)) { IOFree (pending, sizeof (*pending)); return false; }
  struct Operations {
    PolarisPendingWindows &p;
    const PolarisRootLayout &layout;
    uint64_t lunBytes;
    bool prepare (unsigned i) {
      const auto &w = layout.window[i];
      auto *d = new PolarisUfsBlock;
      p.device[i] = d;
      if (!d || !d->init (nullptr) || !d->configureWindow (w.name, w.absolute, w.bytes, lunBytes)) return false;
      p.attached[i] = d->attach (p.owner);
      return p.attached[i];
    }
    bool validate () { return true; } // Parser has already checked both complete payload hashes.
    bool schedule () {
      thread_t thread = nullptr;
      p.owner->retain ();
      if (kernel_thread_start (polarisPublishWindowsThread, &p, &thread) != KERN_SUCCESS) {
        p.owner->release (); return false;
      }
      thread_deallocate (thread); return true;
    }
    void discard (unsigned i) { polarisDiscardWindow (p, i); }
  } ops = { *pending, layout, lunBytes };
  // Do not access pending after successful scheduling; the thread owns it.
  auto result = ufsPrepareRootWindows (ops, 2);
  if (result.phase == UfsRootPhase::Complete) return true;
  IOFree (pending, sizeof (*pending)); return false;
}
