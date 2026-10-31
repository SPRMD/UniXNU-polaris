# iPadOS 17.7.11 root selection

The CI input check pins the OS member `044-76040-038.dmg` to SHA-256
`3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d`.
The root-matching UUID in the iPadOS-only workflow belongs to that OS profile.
It must be reverified when replacing the image pins.

Read-only inspection on 2026-10-31 of the existing local decoded OS window
found a 512-byte-sector GPT. Both primary-header and partition-entry CRCs
passed. The APFS partition starts at byte 17408 and is 6077546496 bytes long;
NXSB reports 1483776 blocks of 4096 bytes. The full decoded disk is
6077580800 bytes, so it is not itself a raw APFS container.

The local public reference `hackios-xnu-kernel/tools/apfs/apfs.py` was used
with a bounded read-only image adapter over that partition. Its checkpoint
selection and object-map lookup (not a magic-byte scan) returned:

- Selected checkpoint transaction: 418.
- Volume index: 0; object ID: 1026; physical block: 15896.
- Role: 1 (system).
- Volume UUID: `04769D26-2CA0-4825-B443-E2E5F88300F2`.

This agrees with `UniXNU-sirius/board.toml` for 21H461. CI installs this UUID
in `/chosen/root-matching` only after verifying the pinned OS inputs.
The normal platform ADT does not request an APFS root volume.

`build-ios-stage.py` now unwraps the checked GPT APFS partition before writing
the SHNGROOT OS window. SystemOS already begins with NXSB and needs no GPT
unwrapping. Older local userdata images can contain the nested GPT and must
not be treated as equivalent to the newly normalized package.

This verifies image geometry and root identity, not physical UFS reads,
successful APFS mount, Data initialization, or Apple userland startup.
