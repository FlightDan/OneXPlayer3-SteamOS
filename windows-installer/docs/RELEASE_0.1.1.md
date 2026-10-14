# OXP3 SteamOS 0.1.1

本版将项目整合版渠道标记为 **stable**。该标签表示项目版本渠道，不代表完整安装流程或所有硬件功能均已验收。

## 更新与验证

- **SteamOS 更新保护：** 安装包含设备修复、插件或账户配置时，在 A/B 两槽启用并检查系统更新保护；暂停 SteamOS 系统镜像更新，保留 Steam 客户端和游戏更新。
- **账户与 SSH 持久化：** 账户、SSH 配置和启动服务链接写入 SteamOS 会迁移的持久 `/etc` 层，不再只依赖可被替换的系统根目录。
- **更新恢复：** 在官方 SteamOS 3.10 根镜像的隔离 QCOW2 写层中，账户、SSH、启动服务和系统更新策略的持久化、只读复核及策略恢复均通过。
- **回归检查：** 45 项 Linux 回归检查通过，覆盖 A/B overlay、账户与 SSH 持久层、仅暂停系统更新、冲突保护和启动激活。
- **B 槽与手柄：** 实机恢复后确认从 SteamOS 3.10 的 B 槽启动。用户确认 Steam 已识别掌机控制器，且自定义按键已恢复。
- **桌面入口语言：** “返回游戏模式”“安装 Waydroid”“重启进入 Windows”会跟随安装器选定语言，不受 KDE 语言设置影响。

## 验收范围与已知限制

完整全新安装直至首次开箱配置（OOBE）尚待测试。自动跨 SteamOS 版本适配尚未实现。默认目标为官方 SteamOS 3.10；该镜像上游更新分支为 `stable`，与本项目整合版渠道相互独立。选择设备集成组件的安装会暂停 SteamOS 系统更新，直到有兼容的适配方案。

此前的 Waydroid 依赖问题仍存在：首次启动路径缺少所需的 `lxc` 和 `dnsmasq` 依赖，Android 镜像还需单独初始化。外部 SD / SSD 安装及其他设备功能仍有各自的验证限制，详见[实现状态](../IMPLEMENTATION_STATUS.md)和[安装指南](INSTALLATION_GUIDE.md)。

## English

This release labels the project integration channel **stable**. That label identifies the project's release channel; it does not mean the complete installation flow or every hardware feature has been validated.

## Changes and validation

- **SteamOS update protection:** When an installation includes device fixes, plugins or account settings, system-update protection is enabled and checked in both A/B slots. SteamOS system-image updates are paused while Steam client and game updates remain available.
- **Persistent account and SSH setup:** Accounts, SSH settings and startup-service links are written through the persistent `/etc` layer that SteamOS migrates, rather than relying only on a replaceable system root.
- **Update restoration:** In an isolated QCOW2 write layer over the official SteamOS 3.10 root image, persistence, read-only verification and restoration passed for accounts, SSH, startup services and the system-update policy.
- **Regression checks:** All 45 Linux regression checks passed, covering A/B overlays, persistent account and SSH setup, system-update-only pausing, conflict protection and startup activation.
- **B slot and controller:** After device recovery, boot from the SteamOS 3.10 B slot was confirmed. The user confirmed Steam recognized the handheld controller and the customized controls were restored.
- **Desktop launcher language:** “Return to Gaming Mode,” “Install Waydroid” and “Restart into Windows” follow the language selected in the installer, independent of KDE's language setting.

## Validation scope and known limits

A complete fresh installation through first-boot setup (OOBE) remains untested. Automatic adaptation across SteamOS versions is not implemented. The default target remains the official SteamOS 3.10 image; its upstream update branch is `stable`, separate from this project's integration channel. Installations that select integration components pause SteamOS system updates until a compatible adaptation is available.

The pre-existing Waydroid dependency issue remains: its first-start path lacks the required `lxc` and `dnsmasq` dependencies, and the Android image requires separate initialization. External SD / SSD installation and other device features retain their own validation limits. See the [implementation status](../IMPLEMENTATION_STATUS.md) and [installation guide](INSTALLATION_GUIDE.md).
