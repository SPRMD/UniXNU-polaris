# Polaris raw APFS windows (2026-10-31)

Build with POLARIS_UFS_BLOCK_RUNTIME=1 (existing --ufs-block-runtime option).
Runtime entry: **native-ufs-windows=1**. Do not combine with root/block/probe/smmu
arguments. root=1 still refuses because root identity/trust is unqualified.
Default probe builds retain no storage-class dependency.

## Discovery

PolarisRootLayout.h is the runtime parser; old RootLayout.h remains for legacy
probes. Only canonical GPT darwin is selected; userdata is never a fallback.
Both GPT headers/arrays must agree and pass CRC. Supported subset: GPT 1.0,
92-byte header, 128-byte entries, at most 128 entries. Tables, usable ranges and
partitions must fit the detected LUN. Overlaps and repeated nonempty names or
unique GUIDs are rejected. No repair or disk writes occur.

SHNGROOT v1 must contain exactly OS/SystemOS, zero reserved fields, read-only
flags and 512-byte sectors. Extents must be 4K aligned and fit the declared
image, partition and LUN. Subtraction-based checks precede addition/multiplication.
Header SHA256 and BOTH complete payload SHA256 values must match before any
device is attached. Reading/hashing multi-GB windows can be slow. Unkeyed hashes
check corruption, not publisher authenticity or root trust.

Only normalized raw APFS is accepted: NXSB at offset 32, 4K APFS blocks,
block_count exactly covering the extent, container-superblock object type,
distinct nonzero container UUIDs. Nested-GPT OS images are refused. This is a
format/geometry guard, not a complete APFS checksum/checkpoint verifier. APFS
owns those checks. Container UUIDs are NOT volume UUIDs and are not copied into
root-matching.

## Actual storage integration

PolarisBlockDevice implements IOBlockStorageDevice with bounded absolute window
offsets. LUN mode reports 4096-byte sectors, windows report 512. Logical reads
may cross physical blocks but never leave a window. All writes remain rejected.

PolarisRootPublisher prepares both devices then schedules a kernel thread.
The reused RootPublication helper starts SystemOS, waits for its actual whole
IOMedia, then starts OS and waits. Preparation/dispatch failures discard all
unstarted objects. Later failure discards only unstarted objects; started
objects remain retained for outstanding asynchronous clients.

The observer queries actual IOMedia services, requiring Whole=true,
Writable=false, correct Size/Preferred Block Size=512, and valid service ancestry
to the exact window device. No fake IOMedia, UUID, BSD name or root-ready service
is constructed. PolarisUfsWindowMediaReady=true means BOTH whole-window media
were observed; it does not certify APFS volume identity, mount or userspace.
Waits are bounded to 30 seconds per window.

Required chain: NativeUfs -> PolarisUfsBlock -> IOBlockStorageDriver -> whole
IOMedia -> APFS. The final kernel/prelink must contain the actual storage driver,
media implementation and matching personality with compatible original ABI.
Linking IOBlockStorageDevice's public base alone does not supply that chain.
Missing matching yields a bounded wait failure, never ready. OS volume UUID
root-matching and TrustCache/ADT remain integrator prerequisites, unchanged here.

## Hard blocker: DMA above 4 GiB

Current ADT kernel RAM starts at 0x100000000. The existing DMA guard requires
an allocated buffer below 4 GiB, so this profile cannot start either runtime.
CAP bit 24 (64AS) and UTRD/PRDT high address words already exist in the transport,
but controller capability alone does not prove that the active apps-SMMU path
accepts and identity-routes above-32-bit addresses. The guard is NOT removed.
Required evidence: actual CAP, SMMU IDR/address widths, active stream routing
and safe firmware handoff. A low DMA pool would need owned/reserved memory and
allocator integration; never borrow firmware pages. Tests do not remove this
blocker and no root-run capability is claimed.

## Primary implementations checked online

Fetched via HTTPS on 2026-10-31. GitHub API hit rate limits; raw source succeeded.

- https://raw.githubusercontent.com/UniXNU/ShengUfs/main/RootLayout.h
  SHA256 3e25127486a5102cd477fcfabd62366a3b3f02bb12a0b8db2294330a4b233484.
  Reused SHNGROOT layout and CRC approach, strengthened for Polaris.
- https://raw.githubusercontent.com/UniXNU/ShengUfs/main/RootPublication.h
  SHA256 3c289b44f4d7c082b3f214eda2d4225f53860dd007f4a89402bdc910f268aeda.
  Reused local lifecycle helper, ordering and ancestry checks.
- https://raw.githubusercontent.com/57UU/UniXNU-sirius/main/package/NativeEmmc.cpp
  SHA256 78014c802acb97856d7466b9598ab8345cea005cb2615c764f0f1cdc299365de.
  Confirms raw APFS window block devices and deferred SystemOS-before-OS start.
- https://raw.githubusercontent.com/apple-oss-distributions/IOStorageFamily/e45fbe30a7879e0b16e26dddb78538f1b00e0bff/IOBlockStorageDriver.cpp
  SHA256 0ae51867bb1be82088733f31e86566435c7c381e1703fa8e9ff5d939850ef3a7.
  instantiateMediaObject and asynchronous registration confirm that whole,
  preferred-sector-size and writable properties derive from device reports.
- https://developer.apple.com/support/downloads/Apple-File-System-Reference.pdf
  Downloaded Apple 2020-06-22 reference. nx_superblock_t confirms geometry and
  container UUID offsets; it does not establish volume identity.

## Validation

Run in WSL: python3 -m unittest discover -s tests -p 'test_ufs*.py' -v.
Production parser tests use independent Python CRC/hashlib fixtures and OpenSSL
SHA256 with ASan/UBSan. Cases cover both GPT CRCs/arrays, capacity/arithmetic
bounds, duplicate GUID/names, overlaps, manifest attributes/hash/overflow,
nested-GPT refusal, container UUID duplication and payload-tail corruption.
Rejected output layouts remain zeroed. Production adapter/lifecycle tests cover
512-byte cross-4K reads, final-sector bounds, preparation/dispatch/start/media
failure cleanup, ordering and ancestor isolation.

Probe/runtime modes also pass cross-clang Darwin syntax checks with the CI
headers and pinned IOStorageFamily headers. No native link, real publication,
APFS/root mount, phone access, commit or push has been performed.
