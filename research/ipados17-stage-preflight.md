# iPadOS 17 阶段静态预检：CI #26 之后的下一个失败点

> 审计基线：仓库 `UniXNU-polaris`，分支 `main`，HEAD `8e52d49`
> （`fix: resolve the renamed prelink kit in the HID recipe`，已包含失败的
> `kits/XnuPrelink` → `kits/NativePrelink` 修复）。
> 审计时间：2026-10-31 18:50 +08:00。审计方式：只读静态审计 + 纯 Python 离线复现。
> 本报告不修改任何脚本；报告落盘文件即本文件。
> 注意：审计期间其它 teammate 正在改 `drivers/ShengUfs/README.md`、
> `research/` 等文件，那些未提交改动不在本报告结论内。

## 结论分级

| 标记 | 含义 |
| --- | --- |
| 已复现 | 本机用真实/最小输入实际跑过，贴出真实报错 |
| 已验证（离线） | 用本地真实输入（pinned kernelcache / BuildManifest / trustcache）核对过，给出可复核数据 |
| 静态推断 | 无法在 Windows 离线验证（需要 macOS+Xcode 或 CI runner），给出推理链与阈值 |
| 未验证 | 明确不知道，禁止当成结论使用 |

---

## 0. 一句话结论

1. **P0（已修复）**：`kits/XnuPrelink` 名字错误已由 `8e52d49` 修复；本报告用 47f526f 旧脚本复现了 CI #26 的
   `ModuleNotFoundError`，并用新脚本在同样目录布局下确认已越过该点（见 §3.6）。
2. **修好之后，hid 脚本本身的纯 Python 假设基本都能过**：ABI 表结构、生成头文件与 checked-in 头文件一致、
   pinned kit 的 `native_prelink.macho()` 接口匹配、编译记录的 RTTI/静态构造假设、pinned kernelcache 的
   prelink roots / AMFI early-security-init 合法性，均已离线核对通过（§2.6、§3）。
3. **下一个可预期的失败点不是 hid 里的 Python 逻辑，而是两类**：
   - **(A) ipados17 独有的首次编译/链接路径**（`ShengUfs --ufs-block-runtime`、
     `PolarisRuntime --with-hid-runtime`、`libPolarisHidInput.a` 强制链接、prelink 真实运行）。
     本次无法离线编译验证，风险中低，失败会以 archive 16/18 或 final link 日志出现（§2.2）。
   - **(B) 资源**：kernel job 要下载并上传 ~7.88 GiB 的 IPSW 成员（§2.3）；紧随其后的
     **ios-stage job 至少需要 ~40 GB 工作磁盘，而 runner 规格是 14 GB、timeout 30 min（§2.4）**。
     即使 kernel job 全绿，这一 job 仍大概率失败，且会浪费一轮完整 CI。
4. 本报告没有找到“在当前 HEAD 上可离线复现的、hid 之后必然触发的构建失败”；
   凡是构建失败项都按推理链标注，不夸大。

---

## 1. 四个 defconfig 的差异与“只在该配置下才执行”的代码路径

对比 `configs/` 四个文件（行号见各 config）：

| 配置键 | polaris | prelink | display | ipados17 | 实际消费点 |
| --- | --- | --- | --- | --- | --- |
| `CONFIG_XNU_CRYPTO_BOOTSTRAP` | source | **prelinked** | source | **prelinked** | `scripts/build-platform-kernel.py:32-35,233-239`；决定是否执行 prelink pass |
| `CONFIG_XNU_TRUST_CACHE_RUNTIME` | – | y | – | y | 只经 `kernel.xnu_env` 变成 XNU 构建 env；仓库脚本无分支 |
| `CONFIG_XNU_SOURCE_MOCKFS` | – | y | – | y | 同上；`build-platform-kernel.py:143` 只在 bootstrap pass 强制关 0 |
| `CONFIG_XNU_NATIVE_UFS` | y | n | y | y | `build-platform-kernel.py:106-113,162-186` |
| `CONFIG_XNU_POLARIS_HID_INPUT` | – | – | – | **y** | `build-platform-kernel.py:36-38,172-176,207-208`；`scripts/build-polaris-hid-input.py` 全脚本 |
| `CONFIG_XNU_NATIVE_MOBILE_DISPLAY` | – | – | y | – | 仓库脚本不读这个键（grep 无命中），只作为 XNU env；`NativeMobileDisplay` archive 在所有配置都构建（`board.toml:34`） |

由此得到“只在 ipados17 下新增的 device-repo 执行路径”：

1. archive 16 `PolarisRuntime` 编译时追加 `-DPOLARIS_WITH_HID_RUNTIME=1`
   （`build-platform-kernel.py:36-38` → `build-arm-driver.py:123-124`）；
2. archive 18 `ShengUfs` 编译时追加 `--ufs-block-runtime`
   （`build-platform-kernel.py:32-35` → `build-arm-driver.py:130-134`）；
3. `scripts/build-polaris-hid-input.py` 整段执行，并把 `libPolarisHidInput.a` 加进
   `XNU_EXTRA_LD_ARCHIVES`（`build-platform-kernel.py:172-176,191-213`）；
4. 与 `polaris_prelink_defconfig` **共享**的 prelink pass（`build-platform-kernel.py:233-239`；
   prelink 配置的差异只是 UFS=n，所以它不走上面 2/3）；
5. workflow 的 `Fetch iPadOS stage inputs` step 和 ios-stage job（`.github/workflows/polaris-build.yml:201-207,423-527`）。

另外两条容易忽略的耦合：

- prelink 依赖 `kits/NativePrelink/patches/*.patch` 给 XNU 打补丁：
  `scripts/build-xnu-4k-baseline.sh:41` 会应用
  `"$ROOT"/patches/xnu/*.patch` **和** `"$ROOT"/kits/NativePrelink/patches/*.patch`。
  这两个 patch 分别定义 `kalloc_sparse_prelink_index_version` 与
  `native_prelink_security_init_version`（pinned kit 3380d300 的
  `patches/xnu-10063.141.1-sparse-index.patch`、`patches/xnu-10063.141.1-security-init.patch`）。
  也就是说：**kit 目录名/内容同时影响 hid import 和 XNU 补丁应用**；如果 kit 缺失，最终 kernel 会
  链接成功但 prelink 报 `Native kernel lacks sparse-prelink index ABI`。
- `board.toml:108` 的 `[kernel.prelink].tool` 与 `build-platform-kernel.py:87-88` 的 submodule
  update 都必须是 `kits/NativePrelink`；pinned upstream `37987aea:.gitmodules` 里正是这个路径
  （submodule commit `3380d3006068cdaab69454b37668e6b532ed2584`）。

---

## 2. 审计结果（按优先级）

### 2.1 P0：已修复点复核（已复现 + 已验证）

| 文件:行 | 触发条件 | 实际失败表现 / 证据 | 建议 | 状态 |
| --- | --- | --- | --- | --- |
| `scripts/build-polaris-hid-input.py:31`（47f526f 版本） | ipados17（HID=y）进入 hid recipe | 旧脚本 `sys.path.insert(0, BUILD_ROOT/'kits/XnuPrelink')`；pinned tree 只有 `kits/NativePrelink`。本机最小布局复现：`ModuleNotFoundError: No module named 'native_prelink'`（§3.6） | 已由 `8e52d49` 改为按内容解析（候选 `kits/NativePrelink`、`kits/XnuPrelink`） | 已复现，已修复 |

复核 fix 本身：`8e52d49` 的 `prelink_kit()`（当前 `build-polaris-hid-input.py:38-50`）先查
`native_prelink.py` / `native_prelink/__init__.py` 存在性，再插入 sys.path；pinned kit 3380d300 根目录
确实有 `native_prelink.py`（已验证，§3.2）。本地测试 `tests/test_polaris_hid_input_source.py` 新增的两个用例
通过（§3.1）。

### 2.2 P1：kernel job 里 hid 之后的首次执行路径（静态推断，无法离线编译）

按执行顺序排列。这里的共同点是：**ipados17 是第一次真正把这些代码交给 macOS/Xcode 编译**，
CI #26 在 hid import 处就停了，所以后续这些步骤此前从未在 CI 执行过。

| # | 文件:行 | 触发条件 | 预期失败表现 / 推理依据 | 建议修法 | 风险 |
| --- | --- | --- | --- | --- | --- |
| P1-a | `build-platform-kernel.py:32-35`；`build-arm-driver.py:130-134` | `XNU_NATIVE_UFS=y` 且 `XNU_CRYPTO_BOOTSTRAP=prelinked`（仅 ipados17） | archive 18/22 会带 `--ufs-block-runtime` 编译 `NativeUfs.cpp` 的 `#if POLARIS_UFS_BLOCK_RUNTIME` 块（`drivers/ShengUfs/NativeUfs.cpp:939-1009`）并先跑 `prepare-storage-headers.py`（`xcrun --sdk macosx`，`prepare-storage-headers.py:37`）。失败形式：`-Werror` 编译错误 / storage 头缺失 / archive 18 失败。历史 CI 日志（run 41188954620）里 archive 18 是**不带**该 flag 完成的；该组合从未在 CI 编译 | 不改脚本；重新 dispatch 后先看 archive 18 日志。若失败，只按真实编译错误修 | 中 |
| P1-b | `build-platform-kernel.py:36-38`；`build-arm-driver.py:123-124` | `XNU_POLARIS_HID_INPUT=y`（仅 ipados17） | archive 16 编译 `PolarisRuntime.cpp` 时宏为 1，`PolarisRuntime.cpp:39-41,177-179` 会引用 `polaris_hid_touch_start()`；该符号由 `PolarisHidProbe.cpp:134` 定义，且 probe 对象在强制加载的 `libPolarisHidInput.a` 中，理论上链接可解析 | 同上，看 archive 16 日志；若链接期才报，再检查 force_load 顺序 | 低-中 |
| P1-c | `build-polaris-hid-input.py:76-223` | 同上 | 已离线核对大部分假设（§2.6）：ABI 表合法、生成头完全一致、pinned kit 的 macho() 接口匹配、编译记录里没有 RTTI、同类 C++ 对象确有 `__GLOBAL__sub_I_*` 与 `__mod_init_func`。剩余不能离线验证：C++ `-Werror` 编译、207 槽 vtable/owned 断言（`build-polaris-hid-input.py:191-207`）、llvm-objcopy/ar 实际执行 | 不改；失败时把 `build/polaris-hid-input/compile.log`、`probe-compile.log` 作为第一证据 | 低 |
| P1-d | `build-platform-kernel.py:177-186,191-213` | ipados17 首次把 `libPolarisHidInput.a` 加进 `XNU_EXTRA_LD_ARCHIVES` 做 final link | 失败形式：undefined symbol（probe 引用未绑定 IOHIDDevice 方法 / 内核私有 API）或 duplicate symbol。静态核对：`OSKextLoadKextWithIdentifier` 在 `OSKext.h` 的 `extern "C"` 块里声明（本地 xnu-work `libkern/OSKextLib.h:710`），`g_kernel_kmod_info`、`kernel_thread_start` 都是内核导出；hid 归档的 `.set` 绝对绑定在 source kernel 链接时也能解析 | 不改；看 `logs/kernel.log` 的 undefined/duplicate 行 | 低-中 |
| P1-e | `build-platform-kernel.py:233-239` → pinned `scripts/unixnu/kernel.py:96-131`（`prelink`） | `CRYPTO_BOOTSTRAP=prelinked`（prelink/ipados17 共用） | 已对 pinned kernelcache 做离线校验：10 个 roots 全部存在；AMFI 有 `AppleSecurityExtension=True`；`early_security_init=0xfffffff005ab4ae0` 落在 AMFI `__TEXT_EXEC`（`va=0xfffffff005aaa000 size=0x205e8`，initprot=5、maxprot=5、4 字节对齐）；`ipsw._identity()` 的 `int(ApChipID,16)` 在真实 BuildManifest 上是字符串 `'0x8011'`/`'0x0C'`，不会 TypeError；解出的 kernelcache 与本地审计文件同一个 sha256。剩余不可离线验证：native kernel 的两个 marker 导出（patch 存在，§1）与占位段布局是否与 pinned kit 完全配套 | 不改；失败时保留 `logs/prelink.log` 与 `kernel-prelinked.json` | 低-中 |

### 2.3 P2：kernel job 的资源风险（静态推断，未验证）

| 文件:行 | 触发条件 | 推理依据 | 建议 | 风险 |
| --- | --- | --- | --- | --- |
| `.github/workflows/polaris-build.yml:201-207`（fetch）+ `:217-244`（upload artifact） | ipados17 dispatch，在 build+prelink 之后 | 该 step 把两个 DMG 写进 `out/native/ipsw/21H461/`：`044-76040-038.dmg` 5,157,406,069 B + `044-76034-038.dmg` 3,303,014,400 B = **8,460,420,469 B ≈ 7.88 GiB**，随后又整目录上传为 artifact（upload-artifact v4 单 artifact 上限 10 GB；按十进制 8.46 GB 计余量约 1.2–1.5 GB，已无多少冗余）。GitHub 官方文档标注 standard macOS runner 存储 **14 GB**（docs.github.com → GitHub-hosted runners reference）；XNU 构建树（`.cache/xnu-work`+ios-obj，含全部 .o/.cpo）与其叠加后，ENOSPC/超时风险不可忽略。本机无法模拟 macOS runner 实际剩余空间 | 先把 DMG 获取移到 ios-stage job（stage 侧重新 `fetch` 到同一缓存），kernel job 只上传 kernel/小文件；若保留现状，在 fetch step 里先 `df -h` 留证 | 高（未验证） |

### 2.4 P3：ios-stage job 会先于任何逻辑失败（高置信静态推断）

即使 kernel job 全绿，`Experimental iPadOS 17 stage`（`polaris-build.yml:423-527`）当前也几乎必然失败，
且失败点在资源而不是脚本逻辑：

| 步骤 | 文件:行 | 推理依据（字节数固定） |
| --- | --- | --- |
| 下载 artifact + `Normalize build artifacts` 复制 DMG | `polaris-build.yml:432-435,465-490` | artifact 里已含 7.88 GiB DMG；注释里的 `cp` 又把两份 DMG 复制到 `out/ios-inputs` → **复制后已 ≥ 15.8 GiB**，而官方 ubuntu-24.04 runner 存储 14 GB |
| OS 解码 + APFS 拆包 | `scripts/build-ios-stage.py:160-184`；`scripts/udif-extract.py` | 5.16 GB DMG → 解码出带 GPT 的 raw disk（同量级）→ 再抽出 APFS 分区 6,077,546,496 B（handoff §2），两份中间文件都保留 |
| SystemOS 解码 | 同上 | ≥ 3.3 GB 输入，另有解码后的 raw |
| `make-userdata-linux.py` 写 darwin-root.img | `scripts/build-ios-stage.py:271-273`；`scripts/make-userdata-linux.py:48-64` | 镜像大小 ≥ 1 MiB + OS 6.08 GB + SystemOS（≥3.3 GB），即 **≥ 9.4 GB** |
| `make-polaris-package.py` 再复制 darwin-root 并做全量 SHA256 | `scripts/make-polaris-package.py:353-357,427-431` | 再 +≥9.4 GB 副本，SHA256SUMS 会把整个包（含 ~10 GB darwin-root）读一遍；随后 check-polaris-package + `sha256sum -c` 又各读一遍 |
| 合计 | — | 保守下限 **≈ 40 GB** 峰值，超出 14 GB 规格一个数量级；job timeout 只有 **30 min**（`polaris-build.yml:428`） |

建议的最小修法（不需要改脚本语义）：
1. 删掉 `out/ios-inputs` 的 DMG 复制，直接把 `out/kernel/native/ipsw/21H461/...` 路径传给 stage builder；
2. kernel job 不上传 DMG，stage job 内用 `scripts/fetch-ios-stage-inputs.py` 取一次；
3. `build-ios-stage.py` 在 unwrap 出 APFS 后删除中间 raw，`make-userdata-linux.py` 写完后删除输入 raw；
4. `make-polaris-package.py` 对 `darwin-root.img` 用硬链接/路径引用而不是 copy，SHA256 只算一次；
5. 把 ios-stage job timeout 提到 60-90 min，或改用 larger runner/拆成“解码 job + 打包 job”。
6. 在 README/研究报告里明确：stage job 变绿只代表离线装配成功，不代表 APFS 可挂载或真机能启动。

### 2.5 P4：不影响构建、但影响证据正确性的风险（静态推断）

| # | 文件:行 | 问题 | 建议 | 证据 |
| --- | --- | --- | --- | --- |
| P4-1 | `board.toml:107-123` | `[kernel.prelink]` 没有 `kernelcache_sha256`；pinned docs 明确说这是“把 native kernel 绑定到合格 component ABI”的手段（`docs/concepts/prelink.md` "Kernelcache pin" 一节；`docs/building.md:105`） | 增加 `kernelcache_sha256 = "f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7"`。这是对 pinned kernelcache 的实测值（本机 inputs/ipsw 文件 sha 与 handoff 一致），不是猜测 | 已验证（离线） |
| P4-2 | `board.toml:111` | `early_security_init = 0xfffffff005ab4ae0` 是硬编码地址；本次已验证它落在 pinned kernelcache 的 AMFI `__TEXT_EXEC` 内且满足 emit_prelink 的全部校验（§2.2 P1-e），但“它是否就是目标初始化函数”未验证 | 不改；在报告里保留"地址范围已验证、语义未验证"的措辞 | 已验证（范围）+ 未验证（语义） |
| P4-3 | `scripts/data/hid-device-abi.json:2` | 描述说 vtable 来自 sheng port 的 prelinked kernel（CI 40829872649）。sheng 的 `board.toml` 里 `os_profile = "ipados-17.7.11-21H461"`，与 polaris 的 iPad7,1/21H461 是同一 OS profile；地址与 `slide=-0x1000000` 也自洽（constructor 0xfffffff004ad94f8+0x1000000 落在 pinned kernelcache 的 `__PLK_TEXT_EXEC`；vptr 0xfffffff005d045c0+0x1000000 落在 `__PLK_DATA_CONST`）。但逐槽语义未在本仓库重新审计（禁止猜地址） | 若后续要真机依赖 HID，需用 pinned ipad7 kernelcache 重跑一次逐槽审计；当前仅作为“范围一致”的证据 | 已验证（范围）+ 未验证（逐槽） |
| P4-4 | `polaris-build.yml:423-527` | artifact 里带有两个 Apple 二进制 DMG（8.4 GB）。构建上没问题，但把闭源 Apple 输入放进 CI artifact 存储/下载链，属于分发与成本问题 | 按 2.4 建议 2 改为 stage job 内实时 fetch，既能修磁盘也能减少 artifact | 静态推断 |

### 2.6 已离线验证通过、不要误改的点（已验证，离线）

| # | 检查 | 结果 | 证据位置 |
| --- | --- | --- | --- |
| V-1 | ABI 表结构 | `methods` 207 条、`instance_bytes=208`、全部 64 位、无重复；生成 header 与 `drivers/PolarisHidInput/OriginalHidDeviceABI.h` 逐字节一致（5243 B） | §3.3 |
| V-2 | pinned kit 的 `native_prelink.macho()` 接口 | 3380d300 的 `native_prelink.py:14-51` 返回 `{kind, segments, commands}`；segment 有 `va/size/command_offset/initprot/maxprot/sections`——与 hid 脚本 175-190 行、emit 的用法一致 | §3.2 |
| V-3 | 编译记录的 RTTI/静态构造假设 | 用同一套 XNU 编译 flag 在本地编译出的 IOKit C++ 对象（`IOConditionLock.cpo`）：**无** `__ZTI/__ZTS`（`-fapple-kext` 下不产生 RTTI），有 `__ZTV15IOConditionLock`、`__GLOBAL__sub_I_IOConditionLock.cpp`、`__mod_init_func` 段。→ hid 脚本的 objcopy globalize 前提成立，`undefined <= bindings` 检查不会被 typeinfo 打败 | §3.3 |
| V-4 | prelink 的 kernelcache 侧校验 | 本地 pinned kernelcache（46,415,872 B，sha256 f18b4df8...）解出 237 个 `_PrelinkInfoDictionary` 条目；`board.toml:112-123` 的 10 个 roots 全部存在；AMFI `AppleSecurityExtension=True`；early-init 地址校验通过；decoded fat 只有 1 个 arm64 slice，slice sha 与 handoff 的 f18b4df8 一致 | §3.4 |
| V-5 | `ipsw._identity()` 的字段类型 | 真实 BuildManifest 的 j120ap/Erase identity：`ApChipID='0x8011'`、`ApBoardID='0x0C'`（**字符串**），pinned `ipsw.py:125` 的 `int(...,16)` 不会 TypeError；`KernelCache` 成员路径 `kernelcache.release.ipad7` | §3.4 |
| V-6 | 后续 stage 需要的 IPSW 成员名 | `StaticTrustCache → Firmware/044-76040-038.dmg.trustcache`、`Cryptex1,SystemTrustCache → Firmware/044-76034-038.dmg.trustcache`；basename 正好是 workflow `test -f out/ios-inputs/044-76040-038.dmg.trustcache` 要的名字 | §3.5 |
| V-7 | stage 纯 Python 步骤（真实输入） | `make-trust-bundle.py` 用真实两个 trustcache 跑通：61,356 B、2 modules、2554 cdhash；`make-polaris-adt.py` 用 workflow 精确参数跑通：11,080 B | §3.5 |
| V-8 | EFI 载荷路径 | `make-ios-esp.py:65-66` 的 `efi/Build/Out/AARCH64-DEBUG/UniXNU.efi`、`loader/build/DarwinBoot/DEBUG_GCC/AARCH64/DarwinBoot.efi` 与 `check-efi.py:68-69` 的构建输出布局一致；workflow 的 `find .../UniXNU.efi` 得到的 EFI_ROOT 正好是这两个路径的父目录 | §3.5 |

---

## 3. 证据与可重放方法

> 所有临时脚本/输出都放在本机工作区 `.local/tmp/stage-preflight/`（不是仓库文件）；
> 仓库只读。下面命令在仓库根目录执行；Windows 测试需按交接文档设置 TEMP/PYTHONPATH。

### 3.1 本地测试基线（已复现）

```powershell
$env:TEMP='C:\Users\James\Documents\ChatGPT\ios_on_mix2s\.local\tmp'; $env:TMP=$env:TEMP
$env:PYTHONPATH='C:\Users\James\Documents\ChatGPT\ios_on_mix2s\.local\pyfix'
python -m unittest discover -s tests -q
```

结果：**Ran 178 tests ... OK (skipped=12)**（8e52d49 上，含 Lead 新增的两个 hid kit 用例）。

### 3.2 pinned tree / kit 的核对

```powershell
git -C out/upstream show 37987aea:.gitmodules        # 含 [submodule "kits/NativePrelink"]
git -C out/upstream ls-tree 37987aea kits/           # kits/NativePrelink -> 3380d300...
```

CI 日志也证明 submodule 注册为 `kits/NativePrelink`（本机保存的 darwin job 日志
`darwin-job-124501574067.log:328-336`：`Submodule 'kits/NativePrelink' ... checked out '3380d300...'`）。
从 GitHub raw 读取 3380d300 的 `native_prelink.py`/**`patches/`** 后确认：
`macho(data, at=0)` 接口匹配，且 `patches/xnu-10063.141.1-sparse-index.patch` /
`...-security-init.patch` 正是 XNU marker 的来源（由 `build-xnu-4k-baseline.sh:41` 应用）。

### 3.3 hid 脚本纯 Python 部分的离线检查（已复现/已验证）

临时脚本复刻 `build-polaris-hid-input.py:76-123` 的头文件生成逻辑后：

```text
methods: 207  instance_bytes: 208  vptr: 0xfffffff005d045c0
all-64bit: True  unique: 207
checked-in header identical to generated: True
generated bytes: 5243  checked-in bytes: 5243
```

用本地已编译的 IOKit C++ 对象（`out/current-upstream-kernel/.../iokit/DEVELOPMENT/IOConditionLock.cpo`，
与 CI 相同的 XNU 编译记录 flag）解析符号表：

```text
defined: __GLOBAL__sub_I_IOConditionLock.cpp, __ZTV15IOConditionLock, ...
sections: __text, __const, __cstring, __mod_init_func(sz=8), ...
undefined RTTI/init: []          # 没有 __ZTI/__ZTS
```

结论：hid 脚本依赖的“无 RTTI、存在全局静态初始化符号与 `__mod_init_func`”前提与真实编译配置一致；
vtable 槽扫描/relocation 解析的字段（section_64 偏移 +56，arm64 外部 UNSIGNED relocation 位域）
与 `native_prelink.macho()` 的字段布局一致。

### 3.4 pinned kernelcache 的 prelink 侧校验（已验证，离线）

输入：`polaris_unixnu_ios17_port/inputs/ipsw/kernelcache.release.ipad7.arm64.macho`
（46,415,872 B，sha256 `f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7`，
与 handoff §5 一致；`kernelcache.release.ipad7.decoded` 是 28 字节头 + 该文件，fat slice 哈希相同）。

用 pinned kit 的 `native_prelink.py`（3380d300）解析后：

```text
entries: 237
ROOT com.apple.kec.corecrypto                      present
ROOT com.apple.driver.AppleARMPlatform             present
ROOT com.apple.filesystems.apfs                    present
ROOT com.apple.driver.AppleMobileFileIntegrity     present
ROOT com.apple.security.sandbox                    present
ROOT com.apple.kext.CoreTrust                      present
ROOT com.apple.security.AppleImage4                present
ROOT com.apple.iokit.IOStorageFamily               present
ROOT com.apple.iokit.IOSurface                     present
ROOT com.apple.iokit.IOHIDFamily                   present
AMFI AppleSecurityExtension = True
AMFI __TEXT_EXEC va=0xfffffff005aaa000 size=0x205e8 initprot=5 maxprot=5
early-init target in AMFI __TEXT_EXEC(rx, filesize): True
```

对照 pinned 工具 `emit_prelink.py`（3380d300）`emit()`：
- `_PrelinkInfoDictionary` 里必须有全部 roots（`plan()` 会 `Missing declared dependency`）；
- early-init 要求 `AppleSecurityExtension is True` 且地址落在模块 `__TEXT_EXEC`、initprot==5、
  `maxprot & 2 == 0`、4 字节对齐（`emit_prelink.py:147-155`）。以上全部满足。

### 3.5 stage 侧纯 Python 步骤（真实输入，已验证）

```powershell
python -B scripts/make-trust-bundle.py `
  --static  <port>/inputs/ipsw/Firmware/044-76040-038.dmg.trustcache `
  --system  <port>/inputs/ipsw/Firmware/044-76034-038.dmg.trustcache `
  --out     trust.bundle
# -> trust.bundle: 61356 bytes, 2 modules, 2554 cdhash entries

python -B scripts/make-polaris-adt.py --output polaris-ios.adt --ram 6 --ipad-identity `
  --include-ufs --trust-cache --root-match-volume-uuid 04769D26-2CA0-4825-B443-E2E5F88300F2
# -> polaris-ios.adt: 11080 bytes
```

BuildManifest（本地 `inputs/ipsw/BuildManifest.plist`，ProductVersion 17.7.11 / 21H461）核对结果：

```text
IDENT j120ap Erase
  ApBoardID = '0x0C' (str)   ApChipID = '0x8011' (str)
  KernelCache               -> kernelcache.release.ipad7
  OS                        -> 044-76040-038.dmg
  Cryptex1,SystemOS         -> 044-76034-038.dmg
  StaticTrustCache          -> Firmware/044-76040-038.dmg.trustcache
  Cryptex1,SystemTrustCache -> Firmware/044-76034-038.dmg.trustcache
```

### 3.6 CI #26 旧失败的最小复现（已复现）

用 47f526f 版本的 hid 脚本 + 一个只含 `kits/NativePrelink/native_prelink.py` 的假 tree：

```text
OLD scripts/build-polaris-hid-input.py --build-root repro/tree
  File ".../old-hid.py", line 32, in <module>
    from native_prelink import macho
ModuleNotFoundError: No module named 'native_prelink'

NEW scripts/build-polaris-hid-input.py --build-root repro/tree   (8e52d49)
  ...（已通过 import / ABI 表 / 生成 header 比对；在假 tree 里按预期停在缺失的
     build/xnu/ios-obj/.../IOPlatformExpert.cpo.json）
```

CI #26 的 `ModuleNotFoundError` 与本机旧脚本复现完全一致；新脚本已越过该点。

---

## 4. 修复顺序建议（最小可执行）

1. **先只做 Lead 的 P0**：`8e52d49` 已提交。push 后只 dispatch 一次
   `polaris_ipados17_defconfig`，**不要在同一轮里再改第三个点**，否则无法归因。
2. 观察顺序（也是本报告的优先级顺序）：
   1. archive 16（`PolarisRuntime` HID 宏）→ 2. archive 18（`ShengUfs` block runtime）
   → 3. `Build source kernel and Polaris drivers` 内的 hid recipe
   → 4. final link → 5. `Prelink pass` → 6. `Fetch iPadOS stage inputs`。
3. **无论第 2 步结果如何，先对 ios-stage job 做磁盘止血**（§2.4）：去掉 `out/ios-inputs` 的 DMG
   复制、DMG 改到 stage job 内 fetch、解码后删中间 raw、package 用硬链接、timeout 提到 60-90 min
   （或 larger runner）。否则即使 kernel job 通过，下一轮 CI 仍会在 stage job 失败，
   并且日志会混杂 ENOSPC/超时，掩盖真实问题。
4. 加 `board.toml [kernel.prelink] kernelcache_sha256`（§2.5 P4-1），并在报告/README 中保留
   “kernel job 通过 ≠ stage job 通过 ≠ 真机能启动”的分级措辞；不要改 `manifest.flashable`。
5. 对 §2.2 的 P1-a/P1-b/P1-c/P1-d/P1-e，**不要预先改脚本**。若新 CI 失败，
   按对应 step 的日志（archive-16/18、polaris-hid-input/compile.log、kernel.log、prelink.log）
   定位后再改；本报告已经排除了最容易误改的几处（§2.6）。

## 5. 明确未验证 / 无法在离线 Windows 验证

- macOS/Xcode 上的实际 C++ 编译与 ld64 链接（P1-a、P1-b、P1-c、P1-d 的实际结果）。
- prelink 的真实执行（emit_prelink 对 native kernel 布局的检查、instruction inventory 扫描、
  输出 ISO 的写入）：只验证了输入侧（kernelcache/roots/AMFI/early-init）与 pinned kit 的接口/补丁链。
- macOS `/usr/bin/compression_tool` 在 runner 上可用：静态依据是 macOS 系统 man page
  （`compression_tool(1)`）与 pinned `ipsw.py:205-212` 的固定路径，未在 CI runner 上实测。
- GitHub runner 的实际剩余磁盘/超时表现：只按官方 14 GB 规格与固定字节数推算，未在 CI 观察；
  因此 §2.3/§2.4 标注为静态推断，不写成“已确认失败”。
- 真实 OS/SystemOS DMG 的 UDIF→APFS 解码本轮没有重跑（单文件 5.16 GB，避免本机长时间占用）；
  handoff §2 的已测量结果（APFS 偏移 17408、长度 6077546496、UUID 04769D26...）是本报告引用依据。
- HID ABI 表的逐槽语义（P4-3）与 early_security_init 目标函数身份（P4-2）：只有范围/格式级别证据。
