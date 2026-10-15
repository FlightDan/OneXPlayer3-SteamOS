# OXP3 SteamOS 0.1.3

0.1.3 目标为 **SteamOS 3.10 / build 20260924.1000**，属于本项目的 **stable** 渠道。发布附件提供完整 Windows x64 安装包 ZIP，不包含 SteamOS 系统镜像。

> **Steam 客户端更新界面：**Animation Changer 插件的路径冲突曾导致更新界面黑屏。0.1.3 已整合修复，用户测试确认更新界面现可正常显示。Steam 客户端更新可能下载数百 MB，请等待进度完成，进度仍在变化时不要强制关机。此项验证不代表完整无人值守全新安装已验收。

> **系统更新风险：**本版新装镜像让 `atomupd` 更新器继续运行并指向必需的私有本地空更新源，因此 SteamOS 系统更新保持暂停，正常运行时不会出现更新候选。若恢复更新或执行官方 SteamOS 系统更新，系统可能从 3.10 回滚至 3.8，并可能覆盖全部 OXP3 适配，包括 Wi-Fi 与手柄支持；兼容性尚未验证。

## 本版变更

- **分区删除兼容修复**：修复 Windows PowerShell 5.1 展开根 JSON 数组时的逐盘匹配问题，避免删除预检错误拒绝目标磁盘。
- **隐藏挂载选择**：新安装不提供共享分区挂载选项；选择安装内容后直接进入“确认方案”，不会被挂载选择阻塞。挂载功能目前仍不可用，代码中的底层实现不代表当前实机可用。
- **安装区位置**：新方案默认靠右，旧保存方案保留原位置。
- **热补丁启动器**：修复专用根目录启动器，使其能找到随包 DLL 和运行时。
- **Steam 客户端更新界面**：修复 Animation Changer 插件路径冲突导致更新界面黑屏的问题；整合后更新界面可正常显示，用户测试通过。
- **新装更新策略**：更新器保留运行，并使用私有本地空更新源；安装器不提供暂停或恢复此策略的 UI。此设置只影响新准备的镜像，不会修改已安装的系统。

## 实机测试与验证范围

当前设备已核对为 B 槽、SteamOS 3.10 / build 20260924.1000、内核 7.2.4。用户已确认 Steam 客户端更新界面修复测试通过。该项验证不代表完整无人值守全新安装或 Steam 登录已验收。

本修复的 Linux 回归、修复夹具和独立审查均通过。其他历史构建检查不代表完整安装已验收，也不证明当前挂载功能可用。

历史版本见 [0.1.2 发布说明](RELEASE_0.1.2.md)、[0.1.1 发布说明](RELEASE_0.1.1.md) 和 [0.1.0 Beta 发布说明](RELEASE_0.1.0_BETA.md)。

## English

Version 0.1.3 targets **SteamOS 3.10 / build 20260924.1000** on the project's **stable** channel. The release package is the complete Windows x64 installer ZIP; SteamOS system images are not bundled.

> **Steam client update screen:** A path conflict with the Animation Changer plugin caused the update screen to appear black. Version 0.1.3 integrates the fix, and the user confirmed the screen now displays correctly. Steam client updates may download hundreds of megabytes; let progress finish and do not force power off while it is advancing. This does not establish a fully unattended fresh-install validation.

> **SteamOS update risk:** The new-install image keeps the `atomupd` updater running against the required private local empty feed, so SteamOS OS updates are held and a healthy updater has no update candidate. Restoring updates or running an official SteamOS system update may roll the system back from 3.10 to 3.8 and overwrite OXP3 adaptations, including Wi-Fi and controller support. Compatibility has not been verified.

### Changes

- **Partition deletion compatibility**: Fixed per-disk matching when Windows PowerShell 5.1 expands a root JSON array, preventing false rejection in deletion preflight.
- **Mount selection hidden**: New installations do not offer shared-partition mounting. After choosing components, the wizard proceeds directly to Review plan; mounting does not block Next. Mounting remains unavailable, and the underlying implementation does not establish current physical usability.
- **Install-region placement**: New plans default to the right; saved plans retain their prior position.
- **Hot-patch launcher**: Fixed the dedicated root launcher so it finds its bundled DLLs and runtime.
- **Steam client update screen**: Fixed a path conflict with the Animation Changer plugin that caused the update screen to appear black. The integrated fix displays the update screen correctly; user testing passed.
- **New-install update policy**: The updater remains running against a private local empty feed; the installer has no UI to pause or resume this policy. This affects newly prepared images only and does not modify an installed system.

### Device test and validation scope

The current device was verified on slot B, SteamOS 3.10 / build 20260924.1000 and kernel 7.2.4. The user confirmed the Steam client update screen fix passed testing. This does not validate a fully unattended fresh install or Steam sign-in.

The Linux regression checks, repair fixture and independent review for this change passed. Historical build checks do not establish complete installation acceptance or current mount usability.

See the historical [0.1.2 release notes](RELEASE_0.1.2.md), [0.1.1 release notes](RELEASE_0.1.1.md) and [0.1.0 Beta release notes](RELEASE_0.1.0_BETA.md).
