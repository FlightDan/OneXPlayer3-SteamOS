# 首次启动：手柄、Decky 与桌面入口

## 2026-10-15 新装联网更新及回退反馈

用户使用解除默认更新屏蔽的测试包重新安装，首次联网更新完成并重启后 Wi-Fi 不可用、手柄显示 Xbox。终端照片确认当前为 A 槽、SteamOS 3.8.28 / build 20260922.1 / 内核 6.18.50-valve2-1-neptune-618-gc7289a96b14d；atomupd 为 active/running，rauc 为 inactive/dead。用户随后切换至 B 槽并确认正常。此次没有获取设备的完整更新日志，但当前版本、槽位及回退结果与官方更新替换适配根系统一致。

这证明解除更新屏蔽不能单独解决首次初始化后的适配保留问题。安装时双槽部署、离线文件验证和模拟回归均不能替代真实联网更新验收。该设备现已核对为 B 槽 / SteamOS 3.10 / build 20260924.1000 / kernel 7.2.4；恢复或运行官方更新仍可能回滚至 3.8 并覆盖适配。不能用共享 home 内的历史安装记录推断 A 槽仍有修复。

后续方案需将系统更新版本与适配兼容性绑定：在非当前槽验证目标系统、内核和适配文件，再试启动；保留已验证的正常槽并提供失败回退。每次开机强制切回旧槽会与官方更新的启动选择冲突，可能反复触发更新，不能作为更新适配的替代实现。首次初始化、Steam 客户端更新及系统镜像更新必须分别验收，不伪造初始化完成或系统版本。

## 2026-10-14 晚间重装回归：系统更新覆盖修复（已定因并恢复）

SSH 只读检查确认：当前从 rootfs-A 启动，系统为 SteamOS 3.8.28 / build 20260922.1，内核为 6.18.50-valve2-1-neptune-618-gc7289a96b14d。当前 `/usr/local/lib` 为空，`oxp3-selected-components.service` 不存在，InputPlumber 未启动，SSH 在手动启动后运行但仍显示 disabled。

同机共享 home 中的 A/B 安装记录均为 SteamOS 3.10 / build 20260924.1000，选择了初始密码、SSH 和设备修复；B 槽有激活记录，InputPlumber、陀螺仪、风扇、CPU、充电及 Decky 等记录为 active，Waydroid 为 refused。A.conf 当前标题是 `SteamOS-A-3.8.28-20260922.1`，B.conf 标题仍是 B，两次启动时间分别为 21:26 和 21:31。桌面文件位于共享 home，因此其存在不能证明当前系统根内的修复仍存在。

后续启动与更新日志确认了原因，用户也确认启动后执行过更新。InputPlumber 曾创建 Valve Steam Deck Controller 并识别 BMI260；RAUC 随后安装官方 `20260922.1-3.8.28.raucb`，记录当前槽 B、目标槽 A 和更新成功，设备之后从 A 启动。只读挂载 B 的 rootfs 后确认仍为 3.10，槽位标记、组件服务及 SSH 启用链接仍存在；当时尚未执行恢复启动验收。

第二次更新为 Steam 客户端：21:33:21 下载完成，21:37:49 安装待处理更新，21:38:07 完成，客户端版本变为 1791918634。这次没有第二条 RAUC 系统安装记录，不是覆盖系统槽的那次更新。21:54 读回 `this-image=A`、`selected-image=A`，普通重启仍会选择 A。

另外，官方 `/usr/lib/rauc/post-install.sh` 的 `sync_var_mountpoints()` 仅从 `/var/lib/overlays/etc/upper` 按保留清单迁移 `/etc` 自定义内容；安装器离线写入根文件系统的 `/etc/shadow` 和服务链接，不等于把它们登记到该持久层。`/usr/local/lib` 中的组件程序也会随官方根文件系统替换消失。成功密码登录只证明该时刻的密码可用，不能单独证明密码来自安装器。

以上结论来自本地 SSH 只读检查、启动日志、RAUC 日志及 `/etc` 迁移检查；原始现场日志不随公开文档发布。本次诊断期间未切换启动槽、关闭更新或重启设备。

安装器固定准备 3.10，但该官方镜像的 `STEAMOS_DEFAULT_UPDATE_BRANCH` 仍为 stable；原路线没有官方更新后的组件保留/迁移及目标版本重新验收链路。现有离线文件复核和前次手动恢复结果不能作为本次重装、联网初始化及重启验收通过的依据。

### 0.1.2 历史修复及验收（旧服务屏蔽方案）

按用户当时明确要求，在 A/B 两槽的持久 `/etc` 层暂时暂停 `atomupd.service` 和 `rauc.service`；仅阻止 SteamOS 系统镜像更新，Steam 客户端和游戏更新配置保留。保存原件后，明确选择 B 槽并执行重启。22:01 的实机复核确认 B / 3.10 / 7.2.4，各输入、陀螺仪、风扇、CPU、充电、功耗及 Decky 服务 active，两项更新服务 masked/inactive。Steam 当前识别唯一的 SteamOS Handheld Controller，VID 28de / PID 12f0；用户明确确认控制器和自定义按键已恢复。Waydroid 的原独立依赖失败仍未解决，不包含在本次验收中。这次人工救援和 0.1.2 新装策略均为历史事实，不代表 0.1.3 沿用此服务屏蔽方式。

实机暂停原件及恢复脚本已保存于设备的受保护恢复目录。脚本恢复两槽原状态并拒绝覆盖后续改动；本次仅保存及语法检查，未执行恢复。更新到不兼容系统仍会丢失设备补丁，恢复前需有对应版本的适配方案。

0.1.2 新安装流程曾在实际 `/etc` overlay 中配置两槽，而不是直接修改下层根目录；写入前独立复核也使用同一只读合并视图。密码、SSH 和启动服务进入官方更新实际迁移的持久层。兼容的 3.10 镜像有任一所选组件或账户配置时，曾强制部署 `system-update-policy`，使用可回退的两个空 service 文件暂停系统更新；选择页、确认方案和完成页披露该政策，每次启动验证实际 systemd mask。该服务屏蔽默认已撤销；0.1.3 最终采用下节的本地空更新源方案，继续暂缓系统镜像更新。旧行为和当时的自动回归均保留为历史，不代表新的新装行为已完成实机验收。

旧安装及旧准备镜像仍可使用恢复入口：`sudo python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py restore --component system-update-policy`。该命令恢复当前槽保存的原服务状态，不切换启动槽；A、B 两槽需分别执行，且已有用户自设的暂停状态会保留。此入口不同于上面的人工实机救援脚本，保持可用以恢复 0.1.2 遗留暂停状态。

`--cli startup-integration-checks` 在无网络的隔离 QEMU 中通过 45 项 Linux 回归，覆盖真实 overlay、白化删除、只读复核、账户/SSH 持久层、仅系统更新暂停、冲突保护、跨槽原件和启动激活。官方 3.10 根镜像另以私有 QCOW2 写层验证密码/SSH/启动服务/更新暂停的真实部署、只读复核及策略恢复通过；原官方镜像只读。这些检查验证的是 0.1.2 旧暂停策略，不是 0.1.3 新装默认。Windows 构建零警告零错误，组件结果检查通过，独立审查后没有未解决的本轮发现。新包整套重新安装、首次联网初始化和新更新策略仍需单独实机验收，不能用这次救援替代。

### 0.1.3 新安装的更新行为

0.1.3 新安装使用必需的 `system-update-hold` 组件：保持 `atomupd` 正常运行，将系统镜像更新查询指向私有本地空更新源；不再采用 0.1.2 的服务屏蔽方式。Steam 客户端和游戏更新配置不变。恢复或执行官方系统更新可能把 3.10 回滚到 3.8，覆盖全部设备适配，导致 Wi-Fi、手柄等失效。

AnimationChanger 1.3.2 会在 Steam 启动前创建 `~/.steam/root/config/uioverrides/movies` 为实目录，导致官方更新器无法找到动画字体。0.1.3 安装器在 `components/plugin_installer.py` 中受保护地处理兼容路径并指向规范目录 `~/.local/share/Steam/config/uioverrides/movies`，由 `integration.py` 调用以避免启动竞态；来源 `CACHE` ZIP 未变。当前设备已应用运行时修复且保留原配置的原子备份。精确官方更新器字体 A/B 隔离测试使用完整离线资源，窗口显示 SteamOS 标志和文字进度，用户确认修复测试通过。更新可能下载数百 MB，请等待进度完成，不要在进度仍变化时强制关机。完整无人值守全新安装未验收；最新构建编号请查包内 `build-info.json`。

2026-10-14 的实机排故发现，组件文件部署完成并不足以保证首次启动可用。本轮修复已进入安装准备、首次启动和镜像复核流程，新的完整安装包才包含这些改动。

| 问题 | 安装流程中的修复 |
| --- | --- |
| 仅识别 Xbox 360，背键及快捷键不可用 | 已选且通过设备/版本检查的输入组件在每次启动时启动 `inputplumber.service`；启动失败单独记录，未选或不兼容的组件不启动 |
| Decky 扫描空目录 | 预装插件统一部署到 `/var/lib/oxp3-installer/decky/runtime/plugins`，与 `PRIVILEGED_PATH` 一致；安装器也转换旧缓存清单中的插件路径 |
| deck 用户不能读取 root 组件 | 插件代码由 root 拥有，目录 0755、常规文件 0644；镜像复核以实际 deck 身份检查读取，不开放私有事务记录 |
| 后端加载但 Steam 没有 Decky 入口 | 选择 Decky 时创建用户拥有的 `~/.local/share/Steam/.cef-enable-remote-debugging`；保留既有标记，新建标记有 A/B 共享恢复记录。参考 [Decky 官方安装器](https://github.com/SteamDeckHomebrew/decky-installer/blob/main/cli/install_release.sh) |
| KDE 缺少返回游戏模式入口或中文乱码 | 基础安装生成 UTF-8 的 `~/Desktop/Return.desktop`，调用系统自带的 `steamos-session-select gamescope`；由 deck 拥有且可执行，保留既有用户入口 |
| HDR / Opti 安装后找不到运行库 | 安装准备和只读复核均按系统 `opt.mount` 绑定 `/home/.steamos/offload/opt`，将运行库写到启动后可见的位置；陌生挂载规则拒绝处理 |

Decky 设置、日志和插件数据继续使用 `/home/deck/homebrew`。Loader 执行文件仍在 root 管理的运行目录，保留自定义服务和 root 插件目录所有权。

## 验证范围

实机修复后，用户确认 Steam Deck 控制器识别与按键恢复、桌面返回游戏模式及 Decky 入口出现。日志确认 12 个插件后端加载、Steam 前端注入成功；以 deck 身份逐项读取插件前端通过，HDR 兼容性检查与 Opti 依赖检查通过。UTF-8 中文名称另行读取验证。

回归覆盖输入服务的已选/未选/缺失/不兼容/启动失败，真实 Linux `/opt` bind mount 与只读复核，严格 umask、插件读取和 Steam 用户目录写权限，以及重复 A/B 准备和既有标记保留。入口为 `--cli runtime-permission-checks`；日志位于 `logs/`，不随源码发布。

上述实机结果来自修复已安装系统；新包整套重新安装、重启和休眠仍需另行验收。Waydroid 首次启动还缺少 `lxc` / `dnsmasq` 依赖，Android 初始化也仍是独立步骤，本轮不将其列为完成。

## 0.1.4 分支：串口与 AutoFlatpaks 重复报错

新准备的 A/B 两槽通过必需的 `serial-console-policy` 文件事务写入 `serial-getty@ttyS0.service.d/90-oxp3-console.conf`。默认跳过 OXP3 不可用的 ttyS0 登录终端；保留现有内核 `console=` 参数及其他 getty。需要真实串口登录时，可显式添加内核参数 `oxp3.serial-console=1`。持久 `/etc`、原件备份、重复准备及冲突保护沿用现有事务。恢复该组件后下次启动恢复原行为。

AutoFlatpaks 修复版为 `1.6.8+oxp3.1`：每秒重新检查 `SystemPowerStore?.batteryState`，状态缺失或 AC 状态尚未初始化时等待后续轮询。有效状态继续走原有事件和更新逻辑，保留卸载时的定时器清理。修复包由 `scripts/patch-autoflatpaks.py` 从固定上游 1.6.8 包重建，包含补丁源码、差异和上游 BSD 许可；保留的部署路径只选修复包，打包排除旧包。0.1.4 现有的第三方插件由用户自装策略保持，未恢复 AutoFlatpaks 默认预装选项。

专项验证入口为 `--cli log-spam-checks`，覆盖串口两槽重复准备、独立运行时恢复、后续管理员修改保护，以及 AutoFlatpaks 部署/恢复。`scripts/test_autoflatpaks_compat.py` 执行实际前端 bundle，验证状态缺失、延迟就绪、AC 切换及卸载。2026-10-16 已对当前运行的 SteamOS 应用同样修复并单独重载 AutoFlatpaks；原件及显式恢复入口保存在 `/var/lib/oxp3-log-spam-repair-20261016-a1/`。未通过重启验证实机持久性，也未生成新的安装器发行包。
