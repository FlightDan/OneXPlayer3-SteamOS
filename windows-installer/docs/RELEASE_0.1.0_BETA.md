# OXP3 SteamOS 0.1.0 Beta

这是 ONEXPLAYER 3 的 Windows x64 安装助手完整运行包。包含应用、便携 .NET、QEMU、离线准备工具和适配组件；不需要另外安装 WSL2、.NET SDK、Node.js 或虚拟机软件。

SteamOS 和 Android 系统镜像不包含在 ZIP 中。SteamOS 镜像从 Valve 官方来源获取；准备 SteamOS 3.10 与部分组件初始化仍需联网。

## 使用

1. 完整解压 ZIP 到本地文件夹，保留所有目录；不要直接在压缩包中运行。
2. 备份数据。如启用 BitLocker / 设备加密，保存恢复密钥并按安装指南暂停保护；在 BIOS / UEFI 关闭安全启动。
3. 运行根目录 `SteamOSInstaller.exe`，处理管理员提示。
4. 为目标 GPT 磁盘准备至少 64 GiB 连续未分配空间，工作空间至少 45 GiB 可用空间，建议 64 GiB。
5. 按向导核对目标磁盘、镜像、组件和启动选项后安装。完整说明见 `docs/INSTALLATION_GUIDE.md`。

## Beta 范围

本包包含工作空间与容量选择、双镜像准备流程、组件权限修复、详细日志导出、可选 rEFInd、安装完成后重启，以及 Windows 桌面的 SteamOS 一次性启动入口。

外部 SD / SSD 安装、rEFInd 固件触控、休眠和全部硬件功能仍需实机验收。已有写盘读回与局部虚拟机检查不能代表当前完整安装和首次启动已通过。分区删除确认后立即执行且不可撤销；停止安装不会回滚写入。

本程序未签名，Windows 可能显示未知发布者提示。只从项目官方 Release 下载；发生问题时从界面导出详细日志，分享前移除个人信息。

## 来源与许可

项目源码：https://github.com/FlightDan/OneXPlayer3-SteamOS

版本和构建信息保存在 `release.json` 与 `build-info.json`。原创代码与文档采用 AGPL-3.0-only；第三方资源保留各自许可证，见 `LICENSE`、`THIRD_PARTY_NOTICES.md`、`licenses/` 及各组件随附材料。第三方源码、补丁和来源记录保留在包内对应目录；运行时分发清单中的待整理项仍如实保留，不能把整个运行包统一标为 AGPL。

问题反馈：https://github.com/FlightDan/OneXPlayer3-SteamOS/issues

## English

Complete portable Windows x64 runtime package for ONEXPLAYER 3. Extract the entire ZIP and run `SteamOSInstaller.exe`; keep all accompanying folders. SteamOS / Android images are not bundled. Internet access is needed for official SteamOS images and some initialization steps.

This is a beta prerelease. Back up data and retain BitLocker recovery keys before modifying partitions or boot settings. Full installation, first boot and all hardware features are not yet comprehensively validated on physical devices. See the bundled guides, build metadata and third-party license/source records.
