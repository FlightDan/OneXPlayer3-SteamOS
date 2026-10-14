# 首次启动：手柄、Decky 与桌面入口

## 2026-10-14 晚间重装回归：系统更新覆盖修复（已定因并恢复）

SSH 只读检查确认：当前从 rootfs-A 启动，系统为 SteamOS 3.8.28 / build 20260922.1，内核为 6.18.50-valve2-1-neptune-618-gc7289a96b14d。当前 `/usr/local/lib` 为空，`oxp3-selected-components.service` 不存在，InputPlumber 未启动，SSH 在手动启动后运行但仍显示 disabled。

同机共享 home 中的 A/B 安装记录均为 SteamOS 3.10 / build 20260924.1000，选择了初始密码、SSH 和设备修复；B 槽有激活记录，InputPlumber、陀螺仪、风扇、CPU、充电及 Decky 等记录为 active，Waydroid 为 refused。A.conf 当前标题是 `SteamOS-A-3.8.28-20260922.1`，B.conf 标题仍是 B，两次启动时间分别为 21:26 和 21:31。桌面文件位于共享 home，因此其存在不能证明当前系统根内的修复仍存在。

后续启动与更新日志确认了原因，用户也确认启动后执行过更新。InputPlumber 曾创建 Valve Steam Deck Controller 并识别 BMI260；RAUC 随后安装官方 `20260922.1-3.8.28.raucb`，记录当前槽 B、目标槽 A 和更新成功，设备之后从 A 启动。只读挂载 B 的 rootfs 后确认仍为 3.10，槽位标记、组件服务及 SSH 启用链接仍存在；当时尚未执行恢复启动验收。

第二次更新为 Steam 客户端：21:33:21 下载完成，21:37:49 安装待处理更新，21:38:07 完成，客户端版本变为 1791918634。这次没有第二条 RAUC 系统安装记录，不是覆盖系统槽的那次更新。21:54 读回 `this-image=A`、`selected-image=A`，普通重启仍会选择 A。

另外，官方 `/usr/lib/rauc/post-install.sh` 的 `sync_var_mountpoints()` 仅从 `/var/lib/overlays/etc/upper` 按保留清单迁移 `/etc` 自定义内容；安装器离线写入根文件系统的 `/etc/shadow` 和服务链接，不等于把它们登记到该持久层。`/usr/local/lib` 中的组件程序也会随官方根文件系统替换消失。成功密码登录只证明该时刻的密码可用，不能单独证明密码来自安装器。

以上结论来自本地 SSH 只读检查、启动日志、RAUC 日志及 `/etc` 迁移检查；原始现场日志不随公开文档发布。本次诊断期间未切换启动槽、关闭更新或重启设备。

安装器固定准备 3.10，但该官方镜像的 `STEAMOS_DEFAULT_UPDATE_BRANCH` 仍为 stable；原路线没有官方更新后的组件保留/迁移及目标版本重新验收链路。现有离线文件复核和前次手动恢复结果不能作为本次重装、联网初始化及重启验收通过的依据。

### 当前修复及验收

按用户明确要求，在 A/B 两槽的持久 `/etc` 层暂时暂停 `atomupd.service` 和 `rauc.service`；仅阻止 SteamOS 系统镜像更新，Steam 客户端和游戏更新配置保留。保存原件后，明确选择 B 槽并执行重启。22:01 的实机复核确认 B / 3.10 / 7.2.4，各输入、陀螺仪、风扇、CPU、充电、功耗及 Decky 服务 active，两项更新服务 masked/inactive。Steam 当前识别唯一的 SteamOS Handheld Controller，VID 28de / PID 12f0；用户明确确认控制器和自定义按键已恢复。Waydroid 的原独立依赖失败仍未解决，不包含在本次验收中。

实机暂停原件及恢复脚本已保存于设备的受保护恢复目录。脚本恢复两槽原状态并拒绝覆盖后续改动；本次仅保存及语法检查，未执行恢复。更新到不兼容系统仍会丢失设备补丁，恢复前需有对应版本的适配方案。

新安装流程在实际 `/etc` overlay 中配置两槽，而不是直接修改下层根目录；写入前独立复核也使用同一只读合并视图。密码、SSH 和启动服务进入官方更新实际迁移的持久层。兼容的 3.10 镜像有任一所选组件或账户配置时，强制部署 `system-update-policy`，使用可回退的两个空 service 文件暂停系统更新。保护缺失、目标服务未知或冲突时终止安装，不作为可跳过项。选择页、确认方案和完成页均披露此政策；每次启动验证实际 systemd mask。重新开放官方系统更新及跨版本自动重新适配仍需另行实现。

未来通过该新组件部署的系统可用 `sudo python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py restore --component system-update-policy` 恢复当前槽的原策略；双槽应分别恢复，已有用户暂停策略保留。此入口不同于上面的本次实机救援脚本。

`--cli startup-integration-checks` 在无网络的隔离 QEMU 中通过 45 项 Linux 回归，覆盖真实 overlay、白化删除、只读复核、账户/SSH 持久层、仅系统更新暂停、冲突保护、跨槽原件和启动激活。官方 3.10 根镜像另以私有 QCOW2 写层验证密码/SSH/启动服务/更新暂停的真实部署、只读复核及策略恢复通过；原官方镜像只读。Windows 构建零警告零错误，组件结果检查通过，独立审查后没有未解决的本轮发现。新包整套重新安装及首次联网初始化仍需单独验收，不能用这次救援替代。

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
