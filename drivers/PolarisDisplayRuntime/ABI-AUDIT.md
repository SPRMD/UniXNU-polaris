# Local compositor ABI audit, 2026-10-31

The CPU archive is linked by the coordinating agent's `3851f2f` integration.
This audit does not modify that integration. Linking the archive does not
connect MobileFramebuffer swap queues to `polaris_display_present`.

## Exact input and identity

Actual input (outside the device repository):

`C:\Users\James\Documents\ChatGPT\ios_on_mix2s\polaris_unixnu_ios17_port\inputs\ipsw\kernelcache.release.ipad7.arm64.macho`

| Item | Observed value |
| --- | --- |
| Size | 46,415,872 bytes |
| SHA-256 | `f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7` |
| LC_UUID | `d6f6e0d2-fe60-38a0-9214-556b7faf8951` |
| Architecture | plain ARM64, subtype 0, MH_EXECUTE |
| MobileGraphics UUID | `18accbf2-bb7c-3461-9245-ed0e6367bffb` |
| IOSurface UUID | `f73d44bb-e674-36e7-a577-83789a86fe7a` |
| Sibling SystemVersion/BuildManifest | `17.7.11`, `21H461` |

Sibling plists are hashed and reported as metadata, **not** a cryptographic
proof that this decoded Mach-O derives from their IPSW member. The manifest
names `kernelcache.release.ipad7`; no signature/decompression-chain validation
is claimed here. SHA/UUID identify the exact file actually read.

## Reproduce

From the device repository, in PowerShell or a shell with Python 3:

```sh
python -B scripts/audit-polaris-display-abi.py --output drivers/PolarisDisplayRuntime/abi/local-kernelcache-audit.json --expect-sha256 f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7 --expect-uuid d6f6e0d2-fe60-38a0-9214-556b7faf8951
python -B -m unittest discover -s tests -p test_audit_polaris_display_abi.py -v
```

Default discovery checks repository-level and project-level `inputs/ipsw` and
rejects ambiguity. Use `--kernelcache <absolute-path>` elsewhere. The tool is
offline and standard-library-only; it does not invoke a compiler/disassembler,
execute reference scripts, modify an input, or contact a phone. Embedded kext
section bytes are read through the outer image's VM mappings, not by treating
embedded file offsets as kernelcache offsets.

Exit 0 means the **evidence report** was generated. Add
`--require-adapter-ready` for an integration gate: the present audit writes the
same report and exits **2**. Parse `adapter_ready`, never `audit_completed`, as
an admission gate. This auditor deliberately has no path that declares an
adapter ready or generates a `.S` binding file. A malformed input or identity
mismatch exits nonzero; callers must check the exit status before consuming
an existing output. Reports have no timestamps and repeat byte-for-byte on
the same host/path/inputs. Absolute input paths differ across hosts.

## Findings supported by local bytes

- The Legacy class name is a standalone string at `0xfffffff0055fbc47`.
  At `0xfffffff0067866a4`, the narrowly decoded ADRP/ADD sequence supplies it
  in x1, supplies superclass metaclass `0xfffffff007b31400` in x2, and supplies
  `0x18a0` in w3. Its BL goes through `0xfffffff0067a2818`, an ADRP/LDR/BR stub,
  to the symbol-identified `OSMetaClass` constructor at `0xfffffff00774b848`.
  This proves the observed size argument; the complete superclass graph is
  still unqualified. Missing matches from the narrow decoder are not evidence
  that other classes are absent.
- A unique candidate vptr `0xfffffff006f38570` is found within this module's
  `__DATA_CONST,__const`, with a zero Itanium two-word prefix, 358 executable
  entries and exactly the reference's nine pure slots. A constructor address
  materialization at `0xfffffff0067865d8` computes table+16. The report records
  all slot targets, kernel export names when present, owner sections, hashes
  of the table and entry instructions. This supports table **location**, not
  all private method prototypes or the table's final compiled subclass ABI.
- Both target kext LC_SYMTAB fields are all zero. Their private method names
  cannot be recovered through the symbol table. Kernel exports are inspected
  separately, including resolution of the metaclass constructor and pure-virtual
  function.
- Sirius's recorded vptr `0xfffffff005f38570` falls in this stock image's
  `__PLK_TEXT_EXEC`. **0/358** raw entries match at that address. Of the local
  candidate's slots, 194 differ from the reference by `+0x1000000`, while the
  other 164 do not. Uniformly sliding the reference table would misbind them.
- All 13 explicit Sirius bindings are listed as **unadmitted**, with their
  actual local owner. Its seven IOSurface accessor addresses are unmapped in
  this input. No inferred slide is applied to these addresses.

The reference may describe a transformed/prelinked image rather than a stock
kernelcache. These mismatches demonstrate different address spaces; they do
not by themselves establish incompatible class semantics. A final-image
relocation map is essential to resolve that distinction.

## Minimum work before a callable adapter

1. Audit the local Legacy base constructors/destructors, superclass graph and
   required overrides (in particular reference slots 184, 188, 213, 249, 288,
   290, 295, 296, 301, 337). Prove prototypes and the compiled subclass vtable,
   not merely matching slot indices. Obtain local addresses for every base
   method/meta object actually referenced by that object file.
2. Locate and validate the seven IOSurface accessors: descriptor, pixel format,
   width, height, stride, planes and allocation. Establish descriptor ownership,
   linear BGRA/BGRX layout and CPU completion before calling the existing
   runtime. Do not apply the apparent module delta to undocumented accessors.
3. Audit the pending/current swap transitions and completion path in this
   exact image: reference object offsets 5472/5480/5488, dimensions 5808/5812,
   and request links 2960/2968 are **hypotheses**, not verified offsets. Prove
   locking, request retention and retirement before modifying a queue or
   reporting swap success.
4. Supply the final prelink/import relocation report and native export map.
   Transform only proven bindings, verify those targets in the final image,
   then implement late class registration after IOSurface/MobileGraphics
   admission. Finish GOP ownership handover and the producer call into
   `polaris_display_present`; CPU copy completion is not a vblank.

These are the unresolved boundaries. No private adapter has been emitted;
the previously tested CPU transfer implementation remains available.

## Public reference provenance

`abi/sirius-reference.json` retains the public 358-slot ABI table and 13 explicit
binding candidates from HuajiFruit/UniXNU-sirius revision
`ac0c900485f3c0cd18de9707579a1cdcd3365503`. On this audit run the pinned raw GitHub
URLs for `scripts/data/mobile-graphics-legacy-abi.json`,
`scripts/build-native-legacy-display.py` and `package/LegacyDisplayProbe.cpp`
all returned HTTP 200; the bytes matched the local reference after newline
normalization. The provenance array records the exact URLs, raw-byte SHA-256s
and lengths. `abi/SIRIUS-LICENSE` retains upstream licensing. The parser's
Mach-O/VM/XML approach follows UniXNU `kits/XnuPrelink/native_prelink.py`.

No Apple binary/code dump is included: the local report contains addresses,
symbol names, metadata and hashes. No board/build/workflow/manifest changes,
phone operations or commits are part of this audit.
