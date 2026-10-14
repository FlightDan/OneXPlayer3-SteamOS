# 首次启动：手柄、Decky 与桌面入口

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
