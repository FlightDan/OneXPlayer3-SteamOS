# OXP3 SteamOS 0.1.2 回归记录

更新：2026-10-15。本页汇总本次实际执行的自动检查和掌机专项。**本文列出的最终自动回归、完整虚拟流程及最新 Opti 载荷的 A/B 整合验证均已完成并通过。** 历史失败、重复批次和设备验收边界分别保留，不用自动通过代替实机验收。

本记录所列自动回归不执行物理分区删除或剩余空间格式化。用户随后反馈已于 **2026-10-15** 在掌机实机测试分区删除、剩余空间 NTFS 格式化和挂载分区到 SteamOS。该挂载反馈未说明每种文件系统、重启后自动挂载、休眠/加密卷或拔卡重连均已验证。现有 home 缩容和掌机完整新装/OOBE 尚未验收。

本轮目标已确认是 **SteamOS 总计 64 GiB**（系统及启动约 24.375 GiB、home 约 39.625 GiB），不是单独把 home 保留为 64 GiB。当前设备的 home 承载多个系统 offload 与不同 mount namespace；没有可用的独立维护介质，本轮只验证挂载并准备发布，真实离线缩容延期，未尝试在线 ext4 缩容。用户随后另反馈已完成掌机实机剩余空间 NTFS 格式化测试。

## 统计口径

表中的断言、布局、unittest 数量和任务数是不同单位，不能相加。重复运行同一 suite、PS5.1 与 PS7 的同一组用例、左右方向复用的 VHD 脚本，以及专项和整合 suite 中的重叠用例，不累计为独立测试总数。15、16、24 项 NTFS 模拟检查分别属于先前与最新批次，最新结果为各 shell 24 项，不相加为 55 项。

原始日志、虚拟磁盘、设备现场记录和绝对路径保留在本地，不随公开源码分发。本页仅公开范围和压缩结论；下表中的 `logs/...`、`work/...` 是本地证据索引，不是公开下载链接。

## 已完成：Windows 构建、界面与规划

| 批次 | 本次结果 | 验证范围 | 本地证据 |
| --- | --- | --- | --- |
| 最新 Debug 构建 | 0 警告 / 0 错误 | 包含 `AlignRight` 默认 false 的兼容字段与最新范围计算 | 构建输出；后续完整虚拟流程使用隔离 Debug 副本 |
| 公开源码候选 | 构建与内容检查通过 | 独立公开 checkout 的 csproj 构建 0 警告 / 0 错误；diff 空白检查通过，本地目录、镜像、密钥、设备地址及 token 模式扫描无命中。发布源码采用补齐最终结果的白名单导出 | `logs/release-0.1.2-public-source-validation.json` |
| WPF 七个 suite | 全部 Exit 0 | 共享页、触屏布局、安装选项、启动准备、结果页、官方下载页面和向导导航 | `logs/release-0.1.2-ui-regression.json` |
| Touch 布局 | 1,282 条断言、112 组布局通过 | 八页、中英文与多尺寸、固定导航、日志导出；不是实体手指触控验收 | `logs/touch-ui-20261015-004600/checks.json` |
| Wizard 导航 | 78 条断言、24 组布局通过 | 任意导航、未完成状态、确认提示及共享页；SVG 为布局重建，非原生像素截图 | `logs/wizard-ui-20261015-004201/checks.json` |
| 共享分区页面 | 13 项通过 | 默认不选、显式跳过、路径复核、语言保留、磁盘身份变化清除旧选择、页脚可见 | `logs/shared-storage-ui-checks.json` |
| 纯规划 CLI | 63 项通过 | 缺省左侧、右侧八分区与左侧余量、序列化、原分区保护、原生 GPT 编码范围拒绝、NTFS 后保留空间重绑定 | `logs/alignment-physical-planning-checks.json` |
| 其他纯 CLI | 13 个任务 Exit 0 | 卷解析、进度、重启生成、恢复、工作空间、组件报告、USB 规划与选择器；其中规划任务以最新 63 项批次为准 | `logs/release-0.1.2-cli-regression.json` |
| 原生 Windows / VHD | 7 个任务 Exit 0 | 原生 GPT、分区写入/恢复、卷锁、VHD smoke、源变化拒绝与安装控制器 | `logs/release-0.1.2-native-regression.json` |
| 下载与来源导航 | 33 条检查通过 | 有界 32 MiB 本机 loopback 服务、自有临时文件及 WPF 来源/进度状态；仅修正测试 fixture，不改变生产下载逻辑 | `work/cli-extra-0.1.2/logs/release-0.1.2-extra-download-regression.json` |

七个 WPF suite 的明细另保存于 `options-checks.json`（78 条）、`boot-setup-20261015-004155/checks.json`（81 条）、`installation-result-checks.json`（68 项）和 `official-download-ui-checks.json`（18 项）。这些数量与布局套件有交叉，不构成额外独立总数。检查未写真实 NVRAM、未请求设备重启，也不代表人工 UAC 操作已验收。

下载专项最初受布局控件查找和实盘准备 overlay 干扰；修正 logical-tree 查找并使用禁止自动磁盘读取的演练 fixture 后，等价底层 `aria2-checks` CLI 完整通过。旧失败日志保留，`-Official` 官方下载路径未在这组本机服务检查中执行。

## Decky 首次默认排序

本版新增首装默认置顶：**OXP3 CPU → OXP3 Fan → OXP3 Battery → Opti2XMX → Restart into Windows**，仅包含实际已安装者，其他已安装插件随后列出。使用真实 Decky 3.2.10 的 `pluginOrder` 显示名数组与 `sortPlugins=false`，目标为包内服务实际使用的 `var/lib/oxp3-installer/decky/runtime/settings/loader.json`。

源码已核对：按字母排序开启时会忽略 `pluginOrder`，未列入数组的插件 `indexOf=-1` 会排到已列者前；因此默认数组覆盖全部实际插件。当前或旧路径有显式排序设置时保留，安装后用户修改不在再次启动或重复准备时重置。A/B 各槽采用独立文件事务。

排序文件的 **9 个单元检查已在掌机真实 Linux 环境通过**，由 deck 普通用户运行，耗时 0.012 秒。仅上传三个检查模块到私有 `/tmp` 目录，完成后清理成功；没有 sudo、没有改变真实 Decky 配置。测试覆盖全插件名顺序、优先项实际存在才列入、旧/当前显式设置保护和异常元数据等逻辑。

新增四项整合文件生命周期检查已在最终 QEMU 整合批次通过，覆盖 A/B 独立设置、首装/重复安装、用户手调保护、恢复和中断事务重试。曾发现组件结果在默认排序写入前已输出，导致最终报告遗漏设置文件，现已修正为 seed 后只发送一次 Decky 结果，最终整合批次确认通过。**真实 Decky UI 的顺序仍未实机验收。** 9 项排序单元在同一最终批次再次通过，不与 SSH 专项或旧 payload 任务累加唯一断言数量。

## 已完成：剩余空间 NTFS

修复前，生产 Windows PowerShell 5.1 的双磁盘 JSON fixture 可复现 `Disk not eligible` / Exit 1。修正根 JSON 数组枚举后恢复正确目标绑定；新增中间空闲区测试又发现 `Math.Max` 错选 Int32 重载，现已显式采用 Int64。

| 批次 | 本次结果 | 验证范围 | 本地证据 |
| --- | --- | --- | --- |
| Windows PowerShell 5.1 模拟 | 最新 24 项通过 | 多磁盘、身份/范围变化、左右布局、中间空闲区、4K 对齐、非法 `AlignRight` 类型、创建后格式化失败的 RAW 分区及记录保留 | `work/format-test-0bab045dded2440a810d1be4c1ed1647/checks.json` |
| PowerShell 7 模拟 | 同组 24 项通过 | 与 PS5.1 同组用例；不重复累计 | `work/format-test-17d472c2379c465da9126760ba7faf0b/checks.json` |
| SteamOS 靠左 / NTFS 靠右 | 真实助手路径通过 | 新建 512 GiB 动态 VHD，保留 64 GiB，NTFS 4096 字节簇、1 MiB / 4K 对齐、原文件保留和共享文件读回 | `work/ntfs-vhd-check-00dc02a3d3a24576b05c455d4d040d5d/result.json` |
| SteamOS 靠右 / NTFS 靠左 | 真实助手路径通过 | 同一验证方法下的新建独立 512 GiB VHD；不是复用前一次磁盘或新增独立断言总数 | `work/ntfs-vhd-check-5e837076fc1f4c22b041cb147cfe8404/result.json` |
| 两个 VHD 清理 | 均独立确认 detached | 结束后未留下附加的测试盘 | `logs/release-0.1.2-alignment-vhd.json` |

VHD 验证执行真实 C# 管理员助手、请求锁、规划、生产 PS5.1 预检、WPF 确认和格式化脚本；确认由测试自动驱动，磁盘枚举通过只绑定新建 VHD 的 inventory adapter 提供。它实际修改测试 VHD，**没有格式化掌机或其他物理磁盘**，也不覆盖人机 UAC/确认过程。

此前 16 项 Storage 模拟及非 Windows 文件系统删除 VHD 结果仍保存在 `logs/release-0.1.2-powershell-regression.json`；这是较早批次，不作为最新 24 项结果的重复加分。

## 已完成：掌机真实内核的 NTFS loop

在当前 SteamOS 内核 `7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9` 上使用自有 **128 MiB 临时 NTFS 文件和 loop 设备**，没有更改物理 GPT、Windows/恢复分区或现有 home。

- `ntfs3` 与 `rw,nosuid,nodev,noexec,uid=1000,gid=1000,fmask=0133,dmask=0022,windows_names` 实际挂载通过；deck 用户的中文文件创建、读取、删除通过。
- 只读 sentinel 保留，deck 写入只读挂载被拒绝。文件实际为 UID/GID 1000、0644，新建目录 0755；该内核 NTFS 卷根目录实际为 **0777**，没有宣称所有目录均为 0755，也未修改卷根 ACL 或强行改变挂载参数。
- 临时运行时 automount 从空闲状态按访问触发成功；不存在的 PARTUUID 在 5 秒设备等待后失败。该测试不代表重启后的 fstab 自动挂载验收。
- 临时 unit 清理、loop 卸载、临时镜像删除及本次加载的 ntfs3 模块恢复卸载均确认完成；home 仍为原 ext4 挂载，GPT 检查正常。

本地原始证据保留在设备现场研究记录，公开报告不携带设备地址、磁盘序列或原始日志。此 loop 结果只证明该真实内核上的临时文件行为，**本身不证明物理共享分区、home 缩容、Windows 休眠/加密卷或双启动后的行为**。另据用户 2026-10-15 反馈，挂载分区到 SteamOS 已完成掌机实机测试；该反馈不扩大为对上述其他场景或所有文件系统的验证。

## 其他设备实验的边界

本轮另保留 DSB 与 Opti2XMX 的设备排查摘要，详见[发布说明的验证范围](RELEASE_0.1.2.md#验证范围与已知限制)。DSB 在一次普通重启后实际为 `Y`，最初约五分钟未观察到 poll error 或相关超时；接手后的同一次启动在 uptime 989.13 秒再次只读核对，参数仍为 `Y`，匹配的内核错误为 0。后一次读回不是第二次重启或受控游戏压力测试。原配置和独立回退保留且未执行回退；这不证明长时间游戏、HDR、休眠唤醒或外接屏兼容，也未改变安装器默认策略。

Opti2XMX 排查包含正在运行游戏的安装拒绝、SSH 预先下载/解压共用缓存，以及随后工具链启动检查。预缓存会影响后续成功，不能证明 Decky 首次下载链路；游戏内加速尚未验证，历史点击错误不能全部归因于游戏占用。排查时的旧版界面只有静态下载/安装提示，没有字节进度或速度；本版后续真实进度改动与验证单独列于下方，不用后续通过覆盖旧现象。这些设备观察不累计为本报告自动测试断言，也不代表新的安装器代码默认已通过实机验收。

## 已完成：Opti2XMX 真实下载进度专项

本版补充下载状态 RPC 与前端进度：显示真实已下载字节、已知总量/百分比和阶段；总量未知时显示已下载量，面板关闭后重开可重新连接当前任务。操作标识、后端实例标识及轮询时序用于拒绝旧响应，超时和失败释放界面忙状态。公开 `components/opti2xmx` 源码、构建前端与缓存载荷已同步；新增 `download_progress.py` 对应 `009.bin`。此前单独插件 ZIP 不作为本次公开发布物。

| 批次 | 本次结果 | 范围与计数 | 本地证据 |
| --- | --- | --- | --- |
| 后端进度单元 | 9 项通过 | 已知/未知/错误长度、逐块进度、缓存命中、重复操作拒绝、并发快照、失败释放与重试 | `logs/opti-progress-backend-windows-final.txt` |
| 前端 | typecheck / build 通过，6 组 VM 检查通过 | 字节/总量显示、重开连接、旧轮询拒绝、实例变化、确认后刷新、挂起请求超时、迟到响应与终态释放；VM 不代表真实 Decky UI 实机操作 | `logs/opti-progress-frontend-final.txt` |
| 冻结源码的真实 Linux 单元 | Exit 0，111 次测试执行通过 | 包含重复导入的基础测试，不能称为 111 个独立场景；最终 10 个模块 SHA 与公开源码一致 | 本地 `research/opti-progress-linux-final-tests-20261015.txt` / `.json` |
| 真实冷下载与热缓存 | 通过 | 自有临时缓存冷下载 55,016,448 bytes，记录逐 chunk 字节增长、解压和完成，再验证热缓存命中；临时目录清理，未改真实游戏或已安装插件 | 本地 `research/opti-progress-linux-tests-20261015.txt` |
| 独立审查与载荷冻结 | 未发现剩余阻断 | 公开源/缓存一致，运行时归档与其他组件项保持一致，源码可重建；属于审查和输入一致性证据，不计额外独立测试数量 | `logs/opti-progress-payload-freeze.json` |

9 项后端、6 组前端、111 次 Linux 执行与较早 110 次 Linux 执行采用不同或重叠口径，不累计总数。真实冷下载证明临时缓存中的后端下载/解压进度，不证明当前已安装 Decky 界面已更新或游戏内 XeSS/XMX 加速通过。最新载荷在官方镜像 A/B 克隆上的恢复、重新部署、独立复核与 hash 验证已通过，详情列于下方。

## 已完成：Linux / QEMU

| 批次 | 当前结果 | 范围与计数 | 本地证据 |
| --- | --- | --- | --- |
| `shared-storage-linux-checks` | 通过 | 13 个 unittest，0 skip；schema、fstab、安全路径与文件事务生命周期 | `logs/python-linux-regression-20261015/unittest-summary.json` |
| `integration-checks` | 通过 | 93 个 unittest，0 skip；独立组件与整合事务，和其他专项存在重叠 | 同上及 `integration-checks.txt` |
| 最终 `integration-checks` | 通过 | 最新 Debug / 冻结源码，8 个 suite 共 110 个 unittest，0 skip / 0 fail，1,075.9 秒；包含槽位 21、Decky 9 与整合 39 项，替代旧 93 项整合批次 | 同目录 `final-integration-result.json`、`final-integration-checks.txt`、`unittest-summary.json` |
| `component-guest-host` | 通过 | 167 个 unittest，0 skip；含 guest 模块与 rEFInd；不与整合 suite 累加唯一总数 | 同上及 `component-guest-host.txt` |
| `integration-delta-checks` | 通过 | CLI Exit 0；不把该任务计为额外独立 unittest 数量 | `logs/python-linux-regression-20261015/cli-results.json` |
| `runtime-permission-checks` | 通过 | CLI Exit 0；实际 deck 身份权限复核，独立任务计数不累加为唯一 unittest 总数 | 同目录 `cli-results.json` 及 `runtime-permission-checks.txt` |
| 启动 / 桌面语言 / home 权限专项 | 通过 | `startup-integration-checks`、`desktop-language-checks`、`home-ownership-checks` 各 Exit 0 | 同目录 `cli-results.json` 及对应日志 |
| `component-skip-checks` | 通过 | CLI Exit 0；安全资源跳过与底层错误停止 | 同目录 `cli-results.json` 及 `component-skip-checks.txt` |
| 最新槽位依赖解析 | 通过 | 实际官方 root 中固定六工具依赖解析通过；最新 21 个槽位 unittest，替代旧 17 项，不相加 | 同目录 `slot-source-inspection-fixed.txt`，任务 Exit 0 / `passed=true` |
| 密码输入专项 | 通过 | `secret-input-checks` Exit 0；真实 QEMU 有/无密码、秘密与状态文件权限、普通用户可访问任务创建的目录/文件、控制台不披露秘密 | 同目录 `cli-results.json` 及 `secret-input-checks.txt` |
| 容量专项 | 通过 | `capacity-checks` Exit 0，340.9 秒；离线 QEMU 新建稀疏 fixture 中保留既有 64 GiB 布局、100 GiB 与小数容量真实 GPT/ext4 扩容、数据保留和源镜像不变 | 同目录 `extra-cli-results.json`、`capacity-checks.txt` 及 `work/capacity-check-2e794af5c698431193920f38c362779b/result.json` |
| 官方 A/B 槽位工具专项 | 通过 | `slot-switch-checks` Exit 0，247.0 秒；实际官方 root 镜像中组件 A/B 生命周期与官方槽位工具 A→B、B→A 调用通过；不等于掌机固件和重启验收 | 同目录 `extra-cli-results.json` 及 `slot-switch-checks.txt` |
| 最新 Opti A/B 载荷整合 | 通过 | QEMU Exit 0 / `passed=true`，777.702 秒，无 timeout/cancel；恢复旧 Opti 后按完整选项重新部署，68 条组件报告均 `files_installed` / 0 skip；每槽独立复核 34 条记录、root 保护/只读核对、10 个安装文件 SHA 一致，9 个源/冻结/打包 SHA 一致 | `logs/python-linux-regression-20261015/final-payload-result.json`；工具工作目录内 `final-progress-payload-bbbc90cacc3549c0bf314dc8d3b69b35/guest-result.json` |
| 完整虚拟工作流 | 通过 | 全新独立工作目录 Exit 0 / `passed=true`，2,476.349 秒（41 分 16 秒）；六个阶段检查通过，内部/外部 VHD 写入读回及两次独立 UEFI 启动至 serial login | `logs/python-linux-regression-20261015/f-full-workflow-result.json`、`f-full-workflow.txt` 及工具工作目录内 `full-virtual-check-a145cb7cabb34262848f6f9d45a54b84/result.json` |

先前完成的 Linux CLI 专项使用此前 Release 主程序，Python payload 从当前源码实时打包；最新 AlignRight 已由独立 Debug 规划、界面与左右 VHD 验证覆盖。最终 110 项整合批次及完整虚拟流程使用包含 AlignRight 的隔离 Debug 副本。整合日志中的串口输出与任务摘要会重复呈现同一组 suite，按 8 个 suite / 110 项计数，不能计为 220 项；也不与旧 93 项批次累加。

最新完整流程工作目录启动前，独立核对 Debug 主程序及 Decky、共享挂载、槽位、guest 验证和 NTFS 脚本等 11 个关键文件的 SHA 一致（`logs/release-0.1.2-full-source-parity.json`）；这是输入一致性检查，不作为业务成功或额外测试断言。后续新增 Opti 下载进度时，该完整流程已经运行，因此没有替换其中的缓存；最新 Opti 载荷在另一个全新镜像克隆上单独执行 A/B 恢复、重新部署及独立复核。完整流程和后续载荷验证分别报告，不能把运行中的旧 Opti 载荷称为最新进度实现已整套重跑。

最新 Opti 验证使用完整流程已准备内部镜像的新克隆，原镜像不修改；A/B 各恢复旧载荷后重新部署，独立复核与安装文件/冻结源码 hash 对照通过。该批次没有额外重做原生磁盘写入或 UEFI 启动，68 条报告、每槽 34 条记录及文件 SHA 对照不累计为独立 unittest 总数。自有 runner 曾在 QEMU 启动前发生语法错误，修正后完整通过；`final-payload-runner-first-syntax-failure.txt` 保留，不把旧错误输出归入通过批次。

首轮组件 fixture 因未包含 `atomupd` / `rauc` vendor unit 出现 4 个测试错误；仅补齐测试 fixture 后重跑通过。旧 runner 的 300 秒预算中断过 rEFInd 检查，改用 900 秒后完整 167 项通过；初次失败和超时日志保留，未归入通过批次。

完整虚拟流程最初因环境网络 Socket 10013 被阻断，尚未写入测试 VHD；获准重试后，准备与组件阶段执行到原生 staging 预检，因 **132,574,666,752 bytes 可用 < 172,335,562,752 bytes 所需**而安全停止。该次 Exit 1 / `passed=false`，没有继续创建写入目标 VHD，不能把 78% 进度或已导出的准备镜像当作完整成功。最新重跑使用另一个容量充足盘上的独立工具工作目录及冻结源码，未放宽或移除空间预检，在原 45 分钟预算内完成并通过，不依赖超时后的补段。失败与预算日志均保留，旧镜像未删除。

通过的完整批次包含恢复镜像导入、官方 3.10 准备、默认组件在 A/B 两槽的部署及独立复核、rEFInd，以及内部/外部原生 VHD 分区写入、读回和两次独立 UEFI 启动至串口登录。六个阶段检查是该流程的里程碑，不累加为六个独立 unittest 或把内部/外部结果再计入原生 suite 总数。它没有执行物理磁盘安装、真实 Windows 操作系统启动、图形 OOBE 或掌机固件验收；最新 Opti 进度载荷由已通过的单独 A/B 克隆批次补充验证。

实际官方 SteamOS 3.10 根镜像还暴露 `slot-switch` 的依赖检查问题：`/usr/bin/steamos-bootconf` 是指向 `/usr/bin/holo-bootconf` 的绝对 symlink，宿主 `Path(root/usr/bin/tool).is_file()` 会在 Alpine 宿主命名空间中误判缺失。修复改为在镜像 root 内解析固定工具的绝对/相对链接，逐层核对 root 归属与不可写权限，并限制 16 次跳转；宿主文件不能替镜像满足依赖。实际镜像依赖检查与包含四项新安全 fixtures 的最新 21 项槽位测试通过。它替代此前 17 项批次，不累加为 38 项，也不代表掌机真实槽位切换和重启验收。

## 尚待验收

上述最终自动回归均已通过。用户反馈分区删除、剩余空间 NTFS 格式化和挂载分区到 SteamOS 已于 2026-10-15 完成掌机实机测试；本记录中的自动检查仍未执行物理分区创建/格式化。用户反馈未说明每种文件系统、重启后的 fstab 自动挂载、真实拔盘/休眠/加密卷行为均已测试。现有 home 离线缩容、实际 Decky UI，以及掌机完整全新安装至 OOBE 仍应独立验收。

功能与操作见[0.1.2 发布说明](RELEASE_0.1.2.md)、[安装指南](INSTALLATION_GUIDE.md)及[实现状态](../IMPLEMENTATION_STATUS.md)。
