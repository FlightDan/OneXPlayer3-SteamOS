# 维护工具验证记录

初始验收日期：2026-10-15；轻量安装与独立打包追加验收：2026-10-16。分支：`codex/steamos-maintenance`。开发与验证使用独立 worktree；未合并、推送或发布。

## 自动化检查

| 环境 | 结果 |
| --- | --- |
| Windows，项目提供的 Python | 304 项：296 通过，8 项平台相关跳过 |
| 隔离 Alpine Linux，Python 3.12.15 | 304 项：301 通过，3 项平台相关跳过 |
| Linux，原生 OpenSSL 3.5.9 | 真实 Ed25519 签名、验签、错误签名拒绝与可重复打包通过 |
| Linux，严格所有权附加检查 | root 私有状态、用户文件 UID/GID、权限、fsync、恢复及符号链接拒绝通过 |

最终 Linux 测试快照的 46 个源码、测试和启动文件 SHA-256 与当前文件一致。虚拟机通过本地 QEMU TCG 运行，只连接只读 Alpine ISO 与只读测试源 FAT，无网络、无宿主实盘；写入发生在 RAM。进程锁测试通过测试专用环境变量放宽模拟器等待时间。

覆盖签名目录与完整包绑定、版本发现与 GitHub 限流/暂时故障回退、下载清理、归档边界、兼容性、依赖、可信旧安装接管、明确选择范围、同版本工具更新、可变配置保留、回退/恢复/中断处理、服务与事务绑定，以及桌面控制器的认证取消、换源后审核失效和摘要绑定。

详细证据位于被 Git 忽略的 `.test-output/windows-current-complete.txt`、`.test-output/linux-current-complete-20261015/`。独立审查对 GTK 工作线程、主线程回调、提权和选择范围未发现阻断问题。

## 实机与载荷

实机为 OXP3、BIOS 5.09、SteamOS 3.10（20260924.1000）、内核 `7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9`，当前 B 槽。仅在用户授权的测试机操作。

- 从明确指定的当前工作区准备项目 0.1.3 载荷：33 项能力、31 项资源、199 个载荷文件，共 323,668,744 字节。rEFInd 和系统槽切换作为独立操作；逐项来源保存在准备报告中。
- 实机全目录预检得到 30 项可用；GM7 项因旧安装元数据与现状冲突而阻断，系统槽切换仍为独立操作，rEFInd 不进入常规安装计划。预检不代表这些组件已全部安装或完成硬件验收。
- 原生 Linux 探测修正并实测了 lsblk 树形输出、Btrfs 设备身份、另一系统槽只读且禁止日志重放的挂载，以及实际系统版本读取。
- 真实 GitHub 请求遇到 API 限流后通过项目公开 Atom 源发现最新项目 0.1.3；维护包尚未公开发布时显示等待维护包，没有误报为全部最新。
- 使用一次性 QA 密钥在设备上构建并验签内部候选包。pass5 清单摘要为 `566b1c95350c218cacee7497e2674192cb6ef27d90a9adf8fbd8e4494b9df81c`；完整包 SHA-256 为 `8b15d3938ba047b6371430fa0dcb26ee36fe5b2f2ce04fc3b4e87bd82325b205`，大小 267,495,102 字节。QA 包包含构建时的文档快照，最终记录以本文件为准。
- 工具独立更新成功，保留现有组件与旧安装选择。文件内容摘要决定独立运行目录，入口最后切换。
- 实机完成键盘组件的应用、回退、再次回退、恢复、再应用、中断恢复检查、再次恢复、再应用，共 8 步。每一步均核对原有自定义 `kwinrc` 内容、0644 权限、UID/GID 1000；挂载、DSB 和原有服务配置不变，系统只读保护始终恢复为 enabled。

早期候选在连续回退时暴露了可变配置丢失问题。已从私有事务前镜像恢复原配置，修复接管前镜像和可变配置比较基线，并增加原文件存在/不存在等回归测试。上述 pass5 实机流程逐步核验通过。保留早期失败记录，不将其计为通过。

实机证据保存在 `.test-output/device-*-pass5*.json`；设备私有原件与事务记录保留用于恢复。未广泛应用硬件修复，未改变现有 DSB 策略。

## 原生界面

用户否决了早期 kdialog 小菜单、原始 JSON 状态和叠加弹窗。现采用设备自带 GTK 3 的原生单窗口，Python 后端负责签名、修改与回退，系统 polkit 负责认证。大按钮、整行选择、触摸滚动、异步进度、内联结果和明确的修改确认已实现。

在真实 KDE 桌面绘制并检查默认尺寸与小窗口。用户随后反馈上下超屏、组件过大：实测显示器缩放后的逻辑工作区为 1129×706、缩放因子为 2，旧窗口最小高度 790，确实超屏。修正为按逻辑工作区决定默认尺寸，压缩 GTK 标题栏与装饰边距；实际窗口为 1089×646，最小为 760×528。主要按钮高 52，项目说明缩小，组件行与上下间距压紧；默认与小窗截图见 `.test-output/compact-touch-*.png`。

按用户要求，可信已安装项目默认隐藏，开关可显示；缺失、损坏或未知项目仍显示。可用且未确认已安装的修复默认全选，插件不默认选择，修复排在前。关闭显示开关会清除隐藏项的显式选择，依赖仍在审核页列出。在线发现不因筛选而额外提权，离线预检复用已授权的真实安装检查。

此轮 314 项全量测试在 Windows 通过 306 项、跳过 8 项；隔离 Linux 通过 311 项、跳过 3 项，原生签名和所有权附加检查通过。证据为 `.test-output/windows-compact-complete.txt` 与 `.test-output/linux-compact-20261015/`。实机 pass6 工具更新与全目录只读预检通过，识别 30 项可信旧安装；新窗口启动正常。用户随后确认紧凑版触屏窗口可用。

随后在实机发现键盘自定义配置的事务比较基线为“原件不存在”，不能用该基线直接比较现文件元数据。pass7 仅补正安装状态识别：保留原件基线的可变配置按当前安全路径、实际存在、正确所有权与安全配置权限确认；缺失或权限异常仍保持可见。新增边界后 11 项安装识别/默认选择测试在 Windows 和实机原生 Linux 均通过；实机重新预检确认 31 项已安装（含自定义键盘），默认隐藏，GM7 冲突仍可见且不可默认勾选。未改事务写入逻辑。pass7 工具更新成功，完整包 SHA-256 为 `d3122f66ee6b37e1c94424fddff1517caa8e5295c3e8190a4af3f2027f085171`。证据见 `.test-output/device-*-pass7.json`。

## 桌面休眠验收

用户确认紧凑版触屏窗口可用后，于 22:45:04 发起桌面模式休眠，22:50:08 通过电源键唤醒。用户确认画面、触屏与维护窗口操作正常。systemd 和内核日志确认 s2idle 正常进入、退出，启动编号不变，无失败服务和待恢复事务。前后核对挂载配置、DSB、旧组件服务、键盘自定义配置及维护入口的 SHA-256、权限和所有权全部一致；只读保护 enabled，DSB 仍为 N。自动检查 timer 与激活服务保持启用。证据为 `.test-output/device-desktop-wake-log.json`、`.test-output/desktop-wake-verification.json` 及前后状态快照。

## 重启发现的陀螺仪问题与修复

首次重启后用户确认游戏模式画面、触屏和按键正常，但自动检查发现旧 `oxp3-gyro.service` 失败。内核先把固定传感器 `i2c-10EC5280:00` 绑定到 `bmi160_i2c`，旧脚本要求设备未绑定而退出；六轴原始值全部为零。本次失败保留在 `.test-output/device-gyro-reboot-failure.json` 等记录中，不计为验收通过。

新增固定设备绑定 helper，保留精确内核、DMI、BIOS 和 InputPlumber 版本条件，仅重绑该传感器，不全局卸载驱动。root 私有启动记录先于模块加载持久化；失败和停止时恢复原绑定。回退或恢复文件前，先验证当前受管 helper 并完成绑定清理、停止 oneshot 服务，再记录完成阶段。中途失败保留两层记录，恢复流程先重试清理；恢复旧 loader 后不尝试用旧脚本重新接管当前绑定。

独立复核发现并修正了模块自动探测前记录顺序、替换 helper 前清理，以及 active oneshot 下 `start` 不重执行的恢复边界。最终 342 项全量测试：Windows 334 通过、8 跳过；隔离 Linux 339 通过、3 跳过。Linux 快照 51 个源码与测试文件摘要全部匹配，真实 OpenSSL 签名和严格所有权附加检查通过。设备 root 环境另外运行 24 项纯 fixture 陀螺仪测试全部通过，无真实 sysfs 写入。普通用户运行该 fixture 因无法设置 root 所有权失败，不计为通过。

证据：`.test-output/windows-gyro-final.txt`、`.test-output/linux-gyro-recovery-final-20261015/`、`.test-output/device-gyro-tests-root-pass8.json`。pass8 候选清单摘要 `78405b6afc07d5b6a55f766ab1f9ad3123c573d12dad0b42ac98387317d59168`，完整包 SHA-256 `694d20b3641e602e04a864798b42439f06af1d8fae708d6c19b115fc8017464b`。先更新工具，再明确选择 gyro（自动包含 input 依赖）；实机预检与应用成功，仅涉及这两个组件。

23:16 重启后自动检查通过：gyro 服务 active/success，固定传感器绑定 `oxp3_bmi260`，六轴读数恢复且持续变化；InputPlumber 使用适配版并记录 `Detected IMU: bmi260`。重复执行 start 返回 active，不改变原绑定恢复记录。当前为游戏模式，自动检查 timer active/enabled，无失败服务、无待恢复文件事务，只读保护 enabled、DSB 为 N。重启前后受保护配置摘要、权限、所有权一致。证据为 `.test-output/device-after-gyro-reboot.json`、`.test-output/device-gyro-after-reboot.json`、`.test-output/gyro-reboot-verification.json`。

## 游戏模式休眠验收与收尾

23:17:16 进入 s2idle，23:49:29 电源键唤醒；用户确认画面、触屏和手柄按键正常。systemd 与内核日志确认休眠成功退出，启动编号仍为 `ea958f5e-a739-4c43-a14c-ea20bda48bfd`。23:50 自动核验无失败服务、无待恢复事务，配置 SHA-256、权限和所有权与休眠前一致，只读保护 enabled，DSB 为 N，更新检查 timer active/enabled。

唤醒后 gyro 服务仍 active/success，固定传感器仍绑定 `oxp3_bmi260`，恢复记录保持 active；8 组采样均可读取六轴数据且非全零，InputPlumber 继续运行。证据为 `.test-output/device-game-wake-log.json`、`.test-output/device-after-game-wake.json`、`.test-output/device-gyro-after-game-wake.json`、`.test-output/game-wake-verification.json`。

本轮设备的原生触屏窗口、桌面休眠、修复后重启及游戏模式休眠验收完成。已删除本次临时 QA 签名私钥，保留候选包、可信公钥、原配置和私有事务记录，供审阅与回退；清理证据为 `.test-output/device-qa-key-cleanup.json`。代码与记录只保存到指定独立 worktree 的 `codex/steamos-maintenance`，未合并、推送或发布。

## 轻量安装入口与独立打包（2026-10-16）

新增 `build_installer.py`、`package_release.py` 和 `oxp3_maintenance/bootstrap.py`。构建命令从显式载荷与发行密钥生成独立 Linux 维护包、版本化签名目录、轻量 shell 安装脚本、公钥及 SHA256SUMS；不会构建 Windows 安装器、修改源码公钥或上传。脚本内嵌六个验证模块与固定公钥，非 root 运行，验证签名目录、完整包私有快照及包内公钥一致性后才启动原生界面，继续沿用界面审核与系统认证。在线及离线入口都拒绝低于已安装维护版的版本；首次安装不声称具有独立的“全局最新版本”证明。

- Windows 367 项全量测试：359 通过、8 项平台相关跳过；隔离 Alpine Linux 367 项：364 通过、3 项平台相关跳过，原生 OpenSSL 与严格所有权附加检查通过。最终快照 56 个源码、测试和启动文件摘要与当前实现一致。
- 新增 25 项专项测试，覆盖打包可重复、错误密钥、私钥材料泄漏拒绝、半成品清理、既有输出保护、自包含脚本隔离执行，以及离线损坏包、同版本缓存替换、目录与版本绑定、公钥不变、降级拒绝、窗口生命周期与临时目录清理。独立安全复核未发现阻断问题。
- OXP3 的 `deck` 用户原生 Bash 验证通过：完整独立打包、脚本 `--help`、既有公钥匹配下的完整离线包验签及重复运行、不同公钥拒绝、损坏归档拒绝。正式 UI 审核与实际安装沿用上一轮已验收的维护后端；本轮未再次执行系统安装或打开窗口。
- QA 轻量脚本为 91,966 字节，完整包 267,504,612 字节，六个发行附件及 SHA256SUMS 核对一致。测试目录明确标记 `release-QA-NOT-FOR-PUBLISHING`，本轮临时签名私钥已删除；不作为生产下载入口。
- 真实公开发布源检查明确返回“尚未提供所选版本的维护包”，退出码 1，未尝试运行未验签内容。公开在线安装成功路径仍需正式资产发布后冒烟验证；离线实包与在线验证逻辑已完成测试。
- 测试前后设备启动编号、配置内容、权限、所有权一致，无失败服务或待恢复事务，只读保护保持 enabled。

证据：`.test-output/windows-bootstrap-complete.txt`、`.test-output/linux-bootstrap-20261016/`、`.test-output/device-bootstrap-native.json`、`.test-output/device-bootstrap-online-pending.json`、`.test-output/bootstrap-final-verification.json`。发行操作见 [独立打包说明](docs/PACKAGING.md)。QA 包内文档是构建时快照，最终验收以本文件为准。

## 2026-10-16：0.1.4 分组清单、独立 Opti 与合并后验证

维护实现 `5917f0e` 已在 CPU/PL2 任务完成后合入 `codex/0.1.4`，合并提交 `cfaea79`。主工作区原有修改保留；README 和安装选项整合维护入口及第三方插件移除规则，其他 306 个已有改动文件逐个核对未变。Windows 安装器既有未提交工作未代为提交。

- 合并后 Windows 全量 406 项：398 通过、8 项平台跳过。隔离 Alpine Linux 全量 406 项：403 通过、3 项平台跳过；真实 OpenSSL、所有权、fsync、软链接附加检查通过。Linux 快照与合并源码仅有 Git 换行符差异，规范化后完全相同。
- Opti 独立分支 `codex/opti2xmx-runtime` / `d37d68d` 已推送至 `FlightDan/Opti2XMX`。普通用户 Linux 127 项全部通过；[GitHub CI](https://github.com/FlightDan/Opti2XMX/actions/runs/38776233956) 的类型检查、前端构建/交互、后端和 ZIP 打包全部通过。首次隔离环境缺少 Bash 导致四项旧测试失败，补齐官方 Bash 依赖后全量复测通过。
- 使用目标工作区最新缓存、独立 Opti 0.2.3-dev ZIP 和显式 0.1.4 元数据生成本地 QA 产物。完整目录含 26 个组件；CPU 后端、功耗适配器和前端逐字节匹配刚完成实机验收的规范源码。QA 签名使用临时测试密钥，私钥已删除，不能作为正式发行包。
- 实包覆盖 WiFi 按需下载、Opti 插件不下载 XMX、显式 XMX 依赖闭包、缓存复用与 root 重新验签。跨 Release 的完整目录升级、旧引擎先升级后再次确认、组件恢复后的更新记录、旧 Opti 运行库所有权迁移和编辑配置回退均有回归测试。只更新插件会保留已有运行库及用户配置。
- OXP3 实机以 deck 普通用户在独立 QA home 测试新运行库安装后端：未发布入口拒绝、截断包拒绝、重试、195,433,378 字节完整包校验、真实 Vulkan 驱动加载和编译器依赖检查、原子配置均通过；模拟冻结 PluginLoader 后仍使用系统 Python。下载响应由本地固定摘要原件提供，未声称公开 HTTP 下载成功。测试后确认现有 runtime.json 和已装插件未变，并移除独立测试运行库。
- 合并后 CPU 前端异步回归通过。目标 CPU 任务已在实机验证 PL1 与 Steam TDP 双向同步、PL2 52/80W 写入，恢复至测试前 40/49W；本轮没有再次调整功耗、重启、修改游戏或替换已装插件。

QA 测得轻量 Bash 入口 125,446 字节，维护入口与常用修复 891,862 字节；独立 Opti ZIP 66,652 字节，维护器 Opti 组件分片 130,738 字节。大型资源和各插件体积见 [0.1.4 发布准备](docs/RELEASE-0.1.4.md)。源码/文档后续变化会影响重新打包体积。

证据保留在独立 worktree 的 `.test-output/windows-014-merged-final.txt`、`linux-014-merged-final-20261016/`、`modular-014-final-20261016/report.json`、`device-opti-runtime-014.json`、`014-integration-provenance.json`、`merge-014-backup-20261016/`。正式 Release 未发布，Opti main 未合并，公网完整下载验收仍待正式资产存在后进行。

## 2026-10-16：正式 0.1.4 发布前回归

- Windows 真实用户环境、原生 OpenSSL：491 项，481 通过、10 项平台条件跳过；Linux root 私有隔离目录、原生 OpenSSL：491 项，476 通过、15 项平台条件跳过。两侧无失败。Windows DPAPI 必须在真实用户配置中验证，受限沙箱缺少该配置时的失败不计为产品通过。
- Windows 测试修正了 Linux OpenSSL 固定路径在测试环境中的映射，以及公钥 PEM 的 CRLF/LF 精确比较；仍执行真实签名和验签，保留输入公钥字节，发行公钥要求规范 LF。27 项专项回归和独立复核通过。
- Linux 首轮测试快照漏带 split-lock 上游许可证，补齐原文件后全量复测通过；保留失败记录，不修改生产许可检查来绕过错误。
- 串口策略的 6 项测试及 AutoFlatpaks 规划、版本收据、事务、恢复、竞争与所有权边界的 5 项联合测试均在 root 私有 Linux fixture 通过。AutoFlatpaks 仅允许精确匹配的已装插件，保留设置/后端/许可证，不重新分发完整第三方插件。
- KDE `[Translations] LANGUAGE=zh_CN` 与区域格式 `LANG=en_US.UTF-8` 并用的中文窗口已在实机临时副本确认；确认区域显示/取消/仅执行一次的 2 项原生 GTK 测试通过。模拟页面截图只用于界面展示，不作为真实安装成功证据。
- 正式 Ed25519 公钥已建立；指纹及密钥保护见 [发布工具记录](docs/PUBLISHER.md)。此次预检确认最终 Opti ZIP 为 0.2.4（帧生成控件保留实验标记），使用公开 v0.2.3 原始运行库固定摘要。正式发布与后续公开入口实机升级尚待完成。

证据保存在忽略目录 `.release-work/windows-maintenance-final-tests-fixed.txt`、`.release-work/linux-maintenance-final-tests-complete.txt`，以及 `research/evidence/maintenance-language-20261016/`。测试均未应用正式维护包或替换设备 QA 信任。

## 2026-10-16：正式维护 Release 与公开下载验证

[maintenance-v0.1.4](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v0.1.4) 已发布，源码提交为 `83877625b35c89c748171112b2444a677d9db38c`。Opti 附件先发布于独立的 `maintenance-assets-v0.1.4`，随后开放维护目录。Windows Latest 仍为 `v0.1.3`；Opti Latest 仍为 `v0.2.4`。

从两个公开 Release 匿名重新下载全部 22 个附件，与正式签名产物逐字节比对通过。重新验证 Ed25519 目录签名、核心包签名与摘要、12 个组件分片的大小、摘要和精确文件清单，以及可选 XMX 原始运行库摘要；目录包含 30 项能力（含独立操作）。实机普通用户也已从公开地址下载 Bash 脚本，摘要一致，尚未据此宣称升级完成。

公开脚本 SHA-256：`b010f70e2af34e10d74ec47f1ee45b82bb0a06dbeda1c31117decb2ea9faa088`；核心包 SHA-256：`31e60e6cd954ab6ae512fada8dc1fad9b623b1d82296ab0af3dd01a097de788b`。证据：`.release-work/public-anonymous-download-verification.json`、`.release-work/public-maintenance-signature-verification.json`。

## 2026-10-16：公开入口实机升级预检

保留完整 QA 状态与原始恢复证据后，设备恢复到公开 0.1.3 项目文件基线并重启。重启后的项目元数据为 0.1.3，启动编排成功，Decky、原生 TDP、CPU、InputPlumber 和陀螺仪服务均为 active，无失败服务，只读保护 enabled。用户配置及第三方插件保留。此步骤没有升级 SteamOS。

公开 Bash 入口在真实 KDE 会话下载并验证正式 0.1.4 核心包，默认显示中文，正确识别已安装项目 0.1.3。按选择下载组件并完成系统认证后，27 项预检中出现两个生产兼容性阻断：GM7 的旧日志模式为 0755，而真实 EFI/VFAT 挂载以 fmask=0077 映射为 0700；风扇配置的旧日志模式为 0600，而公开 0.1.3 风扇程序保存配置使用 0644。工具拒绝应用，没有绕过校验或写入组件。

另一个 Light 目录冲突来自 QA 回滚后留下的两个空目录；独立检查确认无文件，保存私有恢复凭据后移除空目录，未修改插件代码或用户配置。权限认证首次因测试自动化未识别 KDE 弹窗而超时；重试并通过真实密码认证后得到上述预检结果，不把首次超时计为安装成功。

两项接管修复已通过独立安全审查：只允许已证明的 root 所有权、文件权限映射及公开风扇程序摘要，不放宽通用校验。6 项原生 Linux 专项覆盖接管、回退和恢复；在内存中使用冻结补丁只读验证实机 12 个受影响目标通过，旧日志和配置没有修改。Light 的两个空目录已单独处理，不将其当作生产接管缺陷。

公开 GitHub Atom 链接将修订标签中的 `+` 编码为 `%2B`。旧 Bash 在 API 限流时会忽略修订标签并选回首版；新代码仅在可信仓库标签中规范化 `%2B/%2b`，保留其他 URL 与 SemVer 边界以及签名验证。15 项发现回归与独立复核通过。修订使用 build metadata，保留手动同版应用能力，不宣称后台会将其识别成更高版本。

最终 Windows 原生 OpenSSL/DPAPI 全量 500 项：487 通过、13 项平台跳过。Linux 首轮完整测试快照漏带 `prepare-integration.py`，497 项中 480 通过、16 跳过、1 项因缺失该测试依赖报错；记录保留。补齐依赖并加入 Atom 修复后，本地隔离 QEMU 原生 Linux 全量 500 项：485 通过、15 项条件跳过，无失败或错误；6 项新增接管测试与 15 项发现测试全部通过。完整实机安装、重启验收仍待完成。

证据保存在 `research/evidence/maintenance-public-upgrade-20261016/`、`.release-work/windows-maintenance-revision1-final-tests.txt` 和 `.release-work/maintenance-old-installer-atom-counterexample.json`；公开 Release 说明已补充首版阻断情况。

## 尚未完成的验收与发行条件

- 尚未在其他 SteamOS 版本逐项完成硬件验收；便携组件与原生内核相关组件按各自兼容条件处理，不能把可发现/下载等同于可安装全部组件。
- 尚未在实机全面应用 31 项资源，也未完成真实跨项目版本升级和物理断电验收。隔离测试覆盖相应状态机，但不能替代硬件验证。
- 正式维护包已公开发布且公开下载验证通过；0.1.3 → 0.1.4 实机升级待完成。设备 QA 信任配置不作为正式发行配置，不静默替换公钥。
- 所有更新能力仅针对本项目，未升级 SteamOS 或修改官方系统更新策略。

发布前按 [README.md](README.md) 完成剩余验收与签名发行配置。
