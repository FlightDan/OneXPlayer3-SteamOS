# OXP3 SteamOS 0.1.3

0.1.3 目标为 **SteamOS 3.10 / build 20260924.1000**，属于本项目的 **stable** 渠道。发布附件提供完整 Windows x64 安装包 ZIP，不包含 SteamOS 系统镜像。

> **已知问题：首次安装初始化可能长时间黑屏。** 用户掌机测试中，首次启动初始化跳过系统下载后出现长时间黑屏；按住电源键关机并重新开机后进入桌面，Wi-Fi 与手柄正常。SteamOS 精确版本、活动槽位、Steam 登录和完整 OOBE 尚未确认。若在首次安装初始化切换阶段遇到此黑屏，至少等待 **5 分钟**，再按住电源键关机并重新开机。此操作仅适用于初始化黑屏；Windows 镜像写入或真实系统更新正在显示进度时不要强制断电。0.1.3 尚未修复此问题。

> **系统更新风险：**本版新装镜像让 `atomupd` 更新器继续运行并指向必需的私有本地空更新源，因此 SteamOS 系统更新保持暂停，正常运行时不会出现更新候选。若恢复更新或执行官方 SteamOS 系统更新，系统可能从 3.10 回滚至 3.8，并可能覆盖全部 OXP3 适配，包括 Wi-Fi 与手柄支持；兼容性尚未验证。

## 本版变更

- **分区删除兼容修复**：修复 Windows PowerShell 5.1 展开根 JSON 数组时的逐盘匹配问题，避免删除预检错误拒绝目标磁盘。
- **隐藏挂载选择**：新安装不提供共享分区挂载选项；选择安装内容后直接进入“确认方案”，不会被挂载选择阻塞。挂载功能目前仍不可用，代码中的底层实现不代表当前实机可用。
- **安装区位置**：新方案默认靠右，旧保存方案保留原位置。
- **热补丁启动器**：修复专用根目录启动器，使其能找到随包 DLL 和运行时。
- **新装更新策略**：更新器保留运行，并使用私有本地空更新源；安装器不提供暂停或恢复此策略的 UI。此设置只影响新准备的镜像，不会修改已安装的系统。

## 实机测试与验证范围

首次启动实测情况如上。重新开机后桌面、Wi-Fi 和手柄正常；该测试不能确认安装后的 SteamOS 精确版本、活动槽位、Steam 登录或完整 OOBE。新装更新策略尚未通过完整的全新安装与更新周期验证。

当前构建零警告、零错误；根目录 EXE 的 11 组 smoke 检查通过，中英文 10 项真实安装模式的模拟导航断言通过，本轮没有真实磁盘写入。此前挂载隐藏前构建的 17 项挂载 UI 检查属于历史结果，不能验证当前隐藏挂载流程。此前 PowerShell 5.1 分区删除、NTFS 格式化与文件系统识别模拟检查，以及 Linux 16 项 shared-storage、81 项 nonfatal/common 和 PowerShell 5.1 / 7 磁盘枚举模拟检查也有记录。这些检查不代表完整安装已验收，也不证明当前挂载功能可用。

此前报告的实机挂载测试属于历史记录；最新反馈称挂载仍不可用。底层实现支持 GPT，不支持 MBR，也不会自动将分区添加为 Steam 游戏库。

历史版本见 [0.1.2 发布说明](RELEASE_0.1.2.md)、[0.1.1 发布说明](RELEASE_0.1.1.md) 和 [0.1.0 Beta 发布说明](RELEASE_0.1.0_BETA.md)。

## English

Version 0.1.3 targets **SteamOS 3.10 / build 20260924.1000** on the project's **stable** channel. The release package is the complete Windows x64 installer ZIP; SteamOS system images are not bundled.

> **Known issue: first-install initialization may show a long black screen.** In the handheld test, first-boot initialization skipped the OS download and remained black for a long time. After holding the power button to shut down and powering on again, the desktop, Wi-Fi and controller worked. The exact SteamOS version, active slot, Steam sign-in and complete OOBE were not verified. If this happens during the first-install initialization transition, wait at least **5 minutes**, then hold the power button to shut down and power on again. Apply this only to the black initialization transition; do not force power off while Windows is writing the image or while a real system update shows progress. Version 0.1.3 does not fix this issue.

> **SteamOS update risk:** The new-install image keeps the `atomupd` updater running against the required private local empty feed, so SteamOS OS updates are held and a healthy updater has no update candidate. Restoring updates or running an official SteamOS system update may roll the system back from 3.10 to 3.8 and overwrite OXP3 adaptations, including Wi-Fi and controller support. Compatibility has not been verified.

### Changes

- **Partition deletion compatibility**: Fixed per-disk matching when Windows PowerShell 5.1 expands a root JSON array, preventing false rejection in deletion preflight.
- **Mount selection hidden**: New installations do not offer shared-partition mounting. After choosing components, the wizard proceeds directly to Review plan; mounting does not block Next. Mounting remains unavailable, and the underlying implementation does not establish current physical usability.
- **Install-region placement**: New plans default to the right; saved plans retain their prior position.
- **Hot-patch launcher**: Fixed the dedicated root launcher so it finds its bundled DLLs and runtime.
- **New-install update policy**: The updater remains running against a private local empty feed; the installer has no UI to pause or resume this policy. This affects newly prepared images only and does not modify an installed system.

### Device test and validation scope

The first-boot result is described above. The desktop, Wi-Fi and controller worked after power cycling; the exact SteamOS version, active slot, Steam sign-in and complete OOBE remain unverified. The new-install update policy has not been validated through a complete fresh-install and update cycle.

The current build completed with zero warnings or errors. Its root EXE passed 11 smoke-test groups, and 10 physical-navigation assertions passed across Chinese and English; the run made zero physical disk writes. The 17 mount-UI checks from the build before mounting was hidden are historical and do not validate the current hidden-mount flow. Earlier PowerShell 5.1 simulations covered partition deletion, NTFS formatting and filesystem recognition; earlier Linux runs passed 16 shared-storage and 81 nonfatal/common checks, and PowerShell 5.1 / 7 disk-inventory simulations also passed. These checks do not establish complete installation acceptance or current mount usability.

Prior reports of a physical mount test are historical; the latest report says mounting remains unavailable. The underlying implementation supports GPT, not MBR, and does not automatically add partitions as a Steam library.

See the historical [0.1.2 release notes](RELEASE_0.1.2.md), [0.1.1 release notes](RELEASE_0.1.1.md) and [0.1.0 Beta release notes](RELEASE_0.1.0_BETA.md).
