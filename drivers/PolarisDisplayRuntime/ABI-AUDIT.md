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
Mach-O/VM/XML approach follows UniXNU `kits/NativePrelink/native_prelink.py`.

No Apple binary/code dump is included: the local report contains addresses,
symbol names, metadata and hashes. No board/build/workflow/manifest changes,
phone operations or commits are part of this audit.

## 本轮证据（2026-10-31）

本轮只做离线、可复现的主机侧证据：不连接手机、不改 Darwin 专有 C++、不生成
私有绑定。新增工具 abi/collect-local-evidence.py 生成
abi/local-structural-evidence.json（282,825 bytes, SHA-256
04be2647906c7a439365aeb31ec424d4431a5d23c45d334e16fbfbe6a724ab68；同一主机
两次运行字节一致）。它复用主审计脚本的 Mach-O/VM/PRELINK 解析器，退出 0 只
表示证据报告写入成功；adapter_ready 仍为 false。

    python -B drivers/PolarisDisplayRuntime/abi/collect-local-evidence.py \
      --output drivers/PolarisDisplayRuntime/abi/local-structural-evidence.json \
      --expect-sha256 f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7 \
      --expect-uuid d6f6e0d2-fe60-38a0-9214-556b7faf8951

本轮复核（2026-10-31，本机）：主审计 exit 0、报告字节与已签入版本一致；
--require-adapter-ready 仍然 exit 2，输出仍是 adapter_ready: false。没有手机、
没有真机启动、没有 USB 操作。

### 1) Legacy 基类构造/析构、superclass graph 与最终 vtable

**本地字节能确证的部分**

- com.apple.iokit.IOMobileGraphicsFamily 在本镜像中通过 OSMetaClass 构造函数
  导入（stub 0xfffffff0067a2818 -> 0xfffffff00774b848 =
  __ZN11OSMetaClassC2EPKcPKS_j）注册了 12 个类：

  | 类 | instance bytes | superclass（本地解析） | metaclass storage |
  | --- | ---: | --- | --- |
  | IOAVHandlerInternalDisplay | 80 | IOAVHandler | 0xfffffff007b31360 |
  | IOMFBEvtMonTrampoline | 24 | OSObject::gMetaClass | 0xfffffff007b31388 |
  | IOMobileFramebufferUserClient | 1336 | IOUserClient::gMetaClass | 0xfffffff007b313b0 |
  | IOMobileFramebuffer | 144 | IOService::gMetaClass | 0xfffffff007b313d8 |
  | IOMobileFramebufferService | 144 | IOMobileFramebuffer | 0xfffffff007b31400 |
  | IOMFBSwapIORequest | 2976 | OSObject::gMetaClass | 0xfffffff007b314b0 |
  | IOAVHandler | 64 | OSObject::gMetaClass | 0xfffffff007b314d8 |
  | InterruptEventSourceBridge | 24 | OSObject::gMetaClass | 0xfffffff007b31500 |
  | TimerEventSourceBridge | 24 | OSObject::gMetaClass | 0xfffffff007b31528 |
  | UPAsynchronousScheduler | 45152 | OSObject::gMetaClass | 0xfffffff007b31550 |
  | AppleARMParamFIFO | 136 | IOService::gMetaClass | 0xfffffff007b31578 |
  | IOMobileFramebufferLegacy | 6304 | IOMobileFramebufferService | 0xfffffff007b35940 |

- Legacy 的注册调用点在 0xfffffff0067866b8：x1 = name string 0xfffffff0055fbc47，
  x2 = superclass metaclass 0xfffffff007b31400，w3 = 0x18a0 (=6304)，BL 经 stub
  到 0xfffffff00774b848。
- superclass graph 有三条独立证据链，不是单一推测：
  1. 注册 x2 值 0xfffffff007b31400 就是 IOMobileFramebufferService 自己的
     metaclass storage（其 setter 用 ADRP/ADD 物化该地址）；
  2. Legacy vtable 之前的 const header 在 0xfffffff006f38550：
     [0xfffffff007b35940, 0xfffffff007b31400, 0, 0]，vptr = 0xfffffff006f38570，
     与 this class / superclass metaclass 的布局一致；
  3. 构造函数链：Legacy ctor 0xfffffff0067865cc 的第一条 BL 指向
     0xfffffff00677b510（= Service ctor），Service ctor 的第一条 BL 指向
     0xfffffff00677b318（= IOMobileFramebuffer ctor）；Legacy dtor
     0xfffffff006786618 直接 BL 到 0xfffffff00677b55c（= Service dtor 候选）。
  结构链为 Legacy -> Service -> IOMobileFramebuffer -> IOService（Framebuffer 的
  x2 是 GOT 导入的 0xfffffff007942cb8 = __ZN9IOService10gMetaClassE）。Legacy
  6304 = 0x18A0 与公共参考记录的 adapter class size 完全一致。
- 构造函数本体：0xfffffff0067865cc 以 sub sp,sp,#0x30; stp x29,x30 开始，在
  0xfffffff0067865d8 物化 table-0x10（ADRP/ADD，随后 add #0x10），在
  0xfffffff006786608 执行 str x8,[x0] 写入 vptr；析构函数候选
  0xfffffff006786618 保存 this 后调用 Service dtor 候选。这些是本地指令，
  不是符号名推断。
- 本地最终 vtable：0xfffffff006f38570（Family __DATA_CONST,__const），前置
  0xfffffff006f38560/0xfffffff006f38568 为两个零字；358 slots，9 个 pure virtual
  slots [211,213,245,246,306,307,337,338,345]，table SHA-256
  c958b551b17b2af7a4bb798c83e6ca288792af054461148e577371aa71a194fd；358 个
  slot 中 194 个目标落在 Family __TEXT_EXEC,__text、164 个落在内核
  __TEXT_EXEC,__text。12 个类的 vtable 均已定位（含 slot 数）：Legacy 358、
  Service 262、IOMobileFramebuffer 262、IOMobileFramebufferUserClient 187、
  AppleARMParamFIFO 172、SwapIORequest 16 等；Legacy 相对 Service 增加 96 个 slot。
- 本镜像实际装载的 Legacy 子类（重要新证据）：prelink 序号 216 的
  com.apple.driver.AppleMobileDispH9G 定义 direct subclass UnifiedPipeline
  （metaclass storage 0xfffffff007c277a0，instance 9176）；header
  0xfffffff006fd1338 = [0xfffffff007c277a0, 0xfffffff007b35940, 0, 0]，vptr
  0xfffffff006fd1358，同样 358 slots：129 个 override（117 个 Family 方法 +
  12 个内核方法），229 个 slot 与 Legacy 完全相同。另有 AppleCLCD（storage
  0xfffffff007c277c8，9176，vptr 0xfffffff006fd2058）与
  IOMobileFramebufferShim（storage 0xfffffff007c277f8，10240，vptr
  0xfffffff006fd2d58）；H9G 的 IOKitPersonality IOClass = AppleCLCD。H9G 通过
  GOT 0xfffffff006fc7af0 / 0xfffffff006fc7cb0 / 0xfffffff006fc7cb8 分别导入
  Legacy 的 metaclass、C2 构造与 D2 析构。

**本地字节不能确证的部分**

- 无法恢复 358 个 slot 的方法名与原型：两个 Apple kext 的 LC_SYMTAB 全为零，
  内核符号表只有导出符号。slot 身份目前只是表位置、owner 段与指令哈希。
- 析构语义只是结构证据（函数边界、保存 this、调用 super dtor 候选），没有
  成员析构顺序/异常路径证明。
- H9G 类拓扑只确认 header 链接的 storage 对：direct subclass 的名字/大小
  （UnifiedPipeline, 9176）来自同一 setter 的 x0/x1/w3 解码；两个 further
  subclass 的名字映射是候选（一个 init 函数可复用 x1/x2/w3 寄存器，evidence
  JSON 已标注 observed_registration_pairs 与歧义说明）。
- 不能主张某次 Polaris iPadOS 启动会实例化 UnifiedPipeline/AppleCLCD：这取决于
  板级 DT/IOKitPersonality 匹配，本地内核缓存不含该板 DT。

### 2) 七个 IOSurface accessor

**能确证**

- com.apple.iokit.IOSurface UUID f73d44bb-e674-36e7-a577-83789a86fe7a，
  __TEXT_EXEC,__text = 0xfffffff005b96000，size 0x22218 (139800)，section
  SHA-256 6117454cb09b5e36100ee3b1d9b250adfd89fb90684154e059418dd974496c3f。
- 唯一连续 12-getter block 由本地指令 pattern 独立发现（没有加参考 delta），
  其中 7 个与固定参考名对应。每条都是 LDR + RET 0xd65f03c0，负载解码为：

  | accessor | 本地地址 | text 偏移 | 指令 | 解码字段 |
  | --- | --- | --- | --- | --- |
  | descriptor | 0xfffffff005b9ead0 | 0x8ad0 | 0xf9401800 | ldr x0,[x0,#0x30] |
  | format | 0xfffffff005b9ebac | 0x8bac | 0xb9408000 | ldr w0,[x0,#0x80] |
  | width | 0xfffffff005b9ebbc | 0x8bbc | 0xf9402c00 | ldr x0,[x0,#0x58] |
  | height | 0xfffffff005b9ebc4 | 0x8bc4 | 0xf9403000 | ldr x0,[x0,#0x60] |
  | stride | 0xfffffff005b9ebd4 | 0x8bd4 | 0xf9403400 | ldr x0,[x0,#0x68] |
  | planes | 0xfffffff005b9ebf4 | 0x8bf4 | 0xb9409800 | ldr w0,[x0,#0x98] |
  | allocation | 0xfffffff005b9ebfc | 0x8bfc | 0xf9404800 | ldr x0,[x0,#0x90] |

- 参考 binding 地址 + 0x1000000 与上表 7 个地址逐一相等，这是模块 delta 的
  一个独立于 vtable 的交叉验证。PolarisSurfaceABI.h 中的 bytes != 0x22218、
  UUID 与 7 个 {offset,instruction,ret} 校验规则与本轮本地字节一致。

**不能确证**

- descriptor ownership/retention 归属、pixel format 枚举含义、planes 语义、
  BGRA/BGRX 线性布局、CPU completion/fence：本地静态指令不能证明。accessor
  名称来自固定的公开参考，不是从本地符号恢复的。
- 因此 polaris_surface_adapter_create() 的运行时 UUID+指令校验只证明代码位置
  一致，不证明拿到的 IOSurface 已完成且可安全拷出。

### 3) pending/current swap 生命周期与 completion

**能确证**

- 本地确实注册了 IOMFBSwapIORequest，instance size 2976 = 0xBA0（注册点
  0xfffffff00677f130，name 0xfffffff0055fada6），vtable 0xfffffff006f36f60
  （16 slots），构造候选 0xfffffff00677ef88。
- Legacy instance size 6304 = 0x18A0，与参考 adapter 的 class size 相同；
  ABI-AUDIT 中的 request links 2960/2968 恰好落在 SwapIORequest 对象的末尾
  16 字节内，但这不等于已证明它们是 next/prev。
- 参考记录的 7 个 hypothesis offset 在本地 Family/H9G 文本中确实以字面字段
  偏移出现（仅统计编码进 LDR/STR immediate 的访问，GOT-relative 符号加载单独
  剔除）：

  | offset | 参考含义 | 本地编码访问数 | 精确归属到方法入口的 vtable 方法（本地） |
  | ---: | --- | ---: | --- |
  | 0x1560 (5472) | pending/current 候选 | 186 | Legacy slots 312,322,346；AppleCLCD 290,337,346,354 |
  | 0x1568 (5480) | pending/current 候选 | 59 | Legacy 309,311,313,314,322,346；AppleCLCD 290,346 |
  | 0x1570 (5488) | pending/current 候选 | 16 | Legacy 312,346；AppleCLCD 346 |
  | 0x16b0 (5808) | dimensions 候选 | 24 | Legacy 178,247,249,299,322,333（均为 32-bit） |
  | 0x16b4 (5812) | dimensions 候选 | 20 | Legacy 178,248,249,299,322,333（均为 32-bit） |
  | 0xb90 (2960) | request links 候选 | 88（6 个 GOT 相对已剔除） | Legacy 309,311,312,314,322,340,346；AppleCLCD 290,346 |
  | 0xb98 (2968) | request links 候选 | 91 | Legacy 312,340,346；AppleCLCD 290,346 |

- 与 ABI-AUDIT 指定的 10 个参考 slot 求交，得到明确的下一步候选方法：
  slot 249（本地 0xfffffff00679fc8c）访问 0x16B0/0x16B4；slot 290
  （0xfffffff006794030）同时访问 0x1560/0x1568/0xB90/0xB98；slot 337
  （0xfffffff0077785e0，pure virtual）在 AppleCLCD override 中访问 0x1560。
  三者都被本镜像实际子类 override。

**不能确证**

- 字段所属对象：methods 里没有跟踪 base register 到 this 还是 request 参数，
  所以不能断言这些偏移就是 Legacy 的 pending/current 字段。
- 锁定/retain/release/completion 状态机：没有 acquire/release 配对、请求保留
  与退休顺序的证据。不得据此报告 swap 成功，也不得据此改队列。
- 0x16B0/0x16B4 是 width/height 语义、0x1560 等是当前/待切换指针语义，都仍是
  hypothesis，只是偏移存在且被真实方法访问这一层被本地字节支持。

### 4) 最终 import/relocation map、晚类注册与 GOP ownership handoff

**能确证**

- prelink 顺序：IOSurface 序号 31，Family 166，H9G 216；Family 依赖
  com.apple.iokit.IOSurface 52.7.0，H9G 依赖
  com.apple.iokit.IOMobileGraphicsFamily 1.0 与 IOSurface 52.0。即依赖先装载：
  IOSurface 先于 Family，Family 先于 H9G。
- Family 的 Legacy 注册 wrapper 0xfffffff006786550 由最后一个 __mod_init_func
  入口 0xfffffff0067a11ec 调用；同函数随后调用 0xfffffff00679a284。12 个类的
  注册都在 Family 自己的初始化阶段完成。
- 本地 stock 映像的 import 表是已绑定的，可直接导出真实绑定关系：
  - Family：186 个 stubs -> 94 个内核导出、78 个 IOSurface kext 函数、9 个其它
    kext、5 个未解析；GOT 槽为最终地址。
  - IOSurface：139 个 stubs -> 136 个内核导出、3 个未解析。
  - 与显示/GOP 相关的 Family 导入包括 IOMemoryMap::getPhysicalAddress、
    IOMemoryDescriptor::withAddressRange / getPhysicalAddress /
    createMappingInTask、IODeviceMemory::withRange、IOCommandGate::commandGate、
    IOWorkLoop::workLoop、OSMetaClass C2/D2、OSObject C2/D2、
    IOService::getPlatform、IOService::nameMatching（共 34 条 display-relevant）。
- 内核导出侧（本轮逐名核对）：OSMetaClass C2、OSMetaClassMeta::alloc、
  OSMetaClass::preModLoad / checkModLoad / postModLoad / getMetaClassWithName /
  allocClassWithName、OSObject C2、__cxa_pure_virtual、IOService::getProvider、
  IODeviceMemory::withRange / withSubRange / arrayFromList、
  IOMemoryDescriptor::withPhysicalAddress / withAddressRange / map、
  IODTResolveAddressing 全部存在；仅
  __ZN9IOService15registerServiceEPFiP15OSMetaClassBase5IORPCE 未按此名找到。
- H9G 的 provider 合同（来自 prelink 元数据，不是代码推断）：
  IOClass = AppleCLCD、IOProviderClass = AppleARMIODevice、
  IONameMatch = disp0,t8010 | disp0,t8011、
  BacklightMatching = IOPropertyMatch{backlight-control=true}。内核导出存在 PE
  console 原语 IOPlatformExpert::getConsoleInfo(PE_Video*) /
  setConsoleInfo(PE_Video*, unsigned int) 与 PE_parse_boot_argn。

**不能确证**

- stock kernelcache 里没有新加载 adapter 的 relocation/import descriptor：现有
  绑定是 prelink 阶段产物，不能被新 adapter 直接移植；新 adapter 必须走同一
  prelink/kxld 管线（CI 构建）产生自己的绑定。
- 内核导出符号表里没有任何名字含 GOP/gop 的符号；内核缓存不含 UEFI
  framebuffer 对象。现有显示栈是 DT AppleARMIODevice -> AppleCLCD 图，不是
  GOP 句柄图。因此 GOP ownership handoff、provider nub 合同、以及谁调用
  polaris_display_present 都不能由本地 stock 字节确证；必须由板级 firmware/DT
  + 运行时日志证明。
- 无法证明 Family/H9G 能匹配 Polaris 的 DT 节点（镜像中没有 Polaris DT）。

### Sirius 记录与本地 vptr 差异的正面处理

上文 194/164 分裂现在有了可复现的结构解释：

- 194/358 个 slot 的本地目标在 Family kext text，它们相对参考记录的差值全部
  精确等于 +0x1000000（family_target_deltas = ["0x1000000"]）。这个模块相对
  delta 由多条独立证据钉住：参考 __ZTV 前缀地址 + delta = 本地 vtable 前缀、
  参考 C2 + delta = 本地 ctor、7 个参考 accessor + delta = 本地 pattern 找到的
  地址。这是 kext prelink 文本区整体相差 0x1000000，不是对全部地址可用的统一
  slide。
- 164/358 个 slot 的本地目标在内核 text，它们相对参考的差值有 127 个不同值，
  范围 -0x2b0d70 .. -0xd3d28，delta=0 的个数为 0。物理上说明参考记录里的内核
  目标来自另一个内核构建/布局，任何统一 slide 都会错绑。正确做法是按符号身份
  重绑：本地这 164 个目标 164/164 都能在内核导出符号表中解析出名字（例如
  IORegistryEntry::setProperty / attachToParent、OSObject::init、
  IOService::adjustBusy），因此该 164 项应通过本地符号名与参考地址语义逐项
  确认，而不是地址平移。
- 参考 vptr 0xfffffff005f38570 本身：在本地该地址落入一个无关 kext
  （com.apple.driver.DiskImages）的 __TEXT_EXEC,__text，且在该地址 0/358 个
  表项与本地候选相同。参考记录因此只能提供结构（slot 数、顺序、pure slot
  集合），不能提供可直接使用的本地地址。
- 证据 JSON 的 reference_bindings 对 13 条显式 binding 逐条给出 corroboration：
  local-structural-match（gMetaClass、C2、__ZTV）、structural-candidate（D2）、
  independent-instruction-scan-match（7 个 IOSurface accessor）、
  function-boundary-only（vsync_notify、set_refresh_properties）。所有 13 条仍为
  admitted: false，reference_binding_transform.admitted_bindings = 0。

### 本轮新增/更新的证据文件

- abi/collect-local-evidence.py：离线证据收集器，只读、标准库、确定性输出；
  复用主审计的解析器；不发射私有绑定。
- abi/local-structural-evidence.json：本轮全部结构化证据（输入 identity、
  12 类注册/析构/vtable、实际子类 override profile、IOSurface 叶、swap
  hypothesis 扫描、import 绑定、GOP 结论、缺失证据清单）。
- 本轮没有修改 PolarisDisplayRuntime.cpp/.h、PolarisSurfaceABI.h、board/DT、
  manifest 或任何 Darwin 专有 C++；没有手机操作。

### 结论（不夸大）

adapter_ready 仍为 false，--require-adapter-ready 仍按设计失败。本轮把
Legacy vtable/构造析构/父类链/实际子类 override 与 IOSurface 7 个 accessor 的
本地位置提升到了可复现的字节证据，并把 swap 的 reference 偏移缩小到少数可审计
的候选 slot（249/290/337 等）；但方法原型、字段所有权、锁定/完成语义、最终
import/relocation 绑定和 GOP ownership handoff 仍未取得资格证据。不能据此宣称
移动图形已工作或 adapter ready。
