# OneXPlayer3-SteamOS

[简体中文](README.md) | [English](README.en.md)

## 1. 简介

为 **ONEXPLAYER 3 掌机**提供 SteamOS 支持，适配游戏模式、KDE 桌面、手柄与硬件控制，并支持 **Intel XeSS XMX 加速与 XeSS 帧生成（如游戏支持）**。

当前整合版为 **OXP3 SteamOS 0.1.0 Beta**，基于 **SteamOS 3.10**。

发现问题，请发送邮件至 **[dan@devdan.cc](mailto:dan@devdan.cc)**，或提交 [GitHub Issue](https://github.com/FlightDan/OneXPlayer3-SteamOS/issues)。

<details>
<summary>如何正确报告 Bug</summary>

请先查看已有 Issue；一个 Issue 尽量只报告一个问题，并提供以下信息：

- **问题描述**：发生了什么？预期应该怎样？
- **复现步骤**：从启动或打开功能开始，写出能重复触发问题的操作。
- **环境与版本**：ONEXPLAYER 3 型号、BIOS、SteamOS、安装包版本；涉及插件时补充 Decky 和插件版本。
- **游戏相关问题**：游戏名称、Proton 版本、游戏模式或桌面模式，以及 XeSS / XMX / Opti 注入是否开启。
- **发生频率**：每次、偶发，还是仅在重启、休眠唤醒或插拔电源后发生？
- **附件**：相关截图、报错原文和对应时段日志；分享前移除密码、令牌和个人信息。

可以复制这个模板到邮件或 Issue：

```text
问题：
设备 / BIOS：
SteamOS / 安装包版本：
Decky / 插件版本（如适用）：
游戏 / Proton / XeSS设置（如适用）：
复现步骤：
预期结果：
实际结果：
发生频率：
截图 / 日志：
```

</details>

## 2. 适配功能

| 功能 | 适配说明 | 状态 |
| --- | --- | :---: |
| HDR · 游戏模式 / KDE 桌面 | 面板适配的 **1100 / 472 尼特映射** | ✅ |
| 手柄、背键与多功能键 | M1 → L4、Home → L5、M2 → R4、多功能键 → R5，支持 Steam Input 自定义 | ✅ |
| BMI260 陀螺仪 | 游戏内方向与跟随支持；新安装需校准 | ✅ |
| Intel XeSS / XMX | 兼容游戏中的原生 XeSS XMX 加速 | ✅ |
| 刷新率 / VRR | 内屏 30–144 Hz 适配 | ✅ |
| 原生 TDP | Steam 性能菜单 **10–40 W** 调节 | ✅ |
| OXP3 Fan | 固件自动模式与自定义风扇曲线 | ✅ |
| OXP3 CPU | EPP 与核心分组限频控制 | ✅ |
| 性能覆盖层 | CPU / GPU / APU 功耗、风扇与显存信息已正确显示 | ✅ |
| 音量按键 | 音量按键正常 | ✅ |
| Waydroid | Android 应用与游戏模式入口；未充分验证 | 🧪 |
| 重启进入 Windows | [Decky 按钮与桌面快捷方式](windows-installer/docs/WINDOWS_REBOOT.md)，仅下一次启动生效；用户实机重启进入 Windows 已通过 | ✅ |
| OXP3 Battery | 旁通供电与正确的充电上限控制，已验证 | ✅ |
| BE201 Wi-Fi | 无线固件适配；有大量用户报告 Windows 下硬件故障，如果掉驱动请尝试重启 | ⚠️ |
| 双系统启动器 · rEFInd | Windows / SteamOS 启动菜单；用户反馈启动阶段十字键与 A/B 不可用，排查中 | ⚠️ |

✅ 表示已提供对应适配；🧪 表示仍在验证；⚠️ 表示存在已知问题。HDR 使用 Gamma 2.2 映射路径，1100 / 472 为映射参数。新安装、更新、重启及休眠后的支持情况以对应 Release 说明为准。

<details>
<summary>查看 HDR、原生 TDP 与性能覆盖层截图</summary>

**游戏模式 HDR**

![游戏模式 HDR 与亮度控制](windows-installer/docs/screenshots/hdr-game-mode.png)

**原生 TDP · 40 W**

![Steam 原生性能菜单与 40 W TDP](windows-installer/docs/screenshots/native-tdp-40w.png)

**游戏中的 TDP 与性能覆盖层**

![15 W TDP 与游戏性能覆盖层](windows-installer/docs/screenshots/native-tdp-15w.png)

![20 W TDP 与游戏性能覆盖层](windows-installer/docs/screenshots/native-tdp-20w.png)

</details>

<details>
<summary>查看 OXP3 控制插件截图</summary>

![Decky 中的 OXP3 CPU、Fan、Battery 与 Opti2XMX](windows-installer/docs/screenshots/decky-plugins.png)

![OXP3 Fan 风扇曲线控制](windows-installer/docs/screenshots/oxp3-fan.png)

</details>

<details>
<summary>查看 Waydroid 截图</summary>

![Waydroid Android 桌面](windows-installer/docs/screenshots/waydroid-desktop.png)

![Steam 游戏库中的 Waydroid 入口](windows-installer/docs/screenshots/waydroid-steam-entry.png)

</details>

<details>
<summary>查看双系统启动器截图</summary>

Windows / SteamOS 启动菜单截图。当前用户反馈启动阶段十字键与 A/B 不可用，正在排查。

![rEFInd 双系统启动器 · Windows / SteamOS 启动选择](windows-installer/docs/screenshots/dual-boot-launcher.png)

</details>

## 3. 独家插件 · Opti2XMX

**[Opti2XMX](https://github.com/FlightDan/Opti2XMX)** 是为这套适配开发的 Decky 插件，可为兼容的游戏直接提供原生的 **XeSS XMX 加速与 XeSS 帧生成**，并为其他兼容游戏提供支持 **XeSS 帧生成的 OptiScaler**。

- 原生 XeSS 游戏可直接配置 XMX；其他兼容游戏可通过 OptiScaler 接入。
- XMX 加速与 Opti 注入独立开关，支持安装、版本切换、回退和卸载。
- 提供超分、帧生成输出及相关设置，支持中英文界面。

XMX 需要兼容的 Intel 硬件及配套运行环境；仅安装插件不足以启用。帧生成支持取决于游戏、驱动与 Proton。测试游戏原生 XeSS 帧生成时，应关闭 Opti 注入。

<details>
<summary>查看 Opti2XMX 与原生 XeSS 游戏截图</summary>

**Opti2XMX · 按游戏开启 XMX**

![Opti2XMX 的 XMX 加速开关](windows-installer/docs/screenshots/opti2xmx-xmx.png)

**《黑神话：悟空》原生 XeSS 与帧生成设置**

![黑神话悟空中的 XeSS 与帧生成选项](windows-installer/docs/screenshots/native-xess-settings.png)

**游戏画面**

![开启相关配置后的黑神话悟空游戏画面](windows-installer/docs/screenshots/xess-gameplay.png)

</details>

## 4. 安装方法

完整 Windows x64 安装应用 ZIP 通过 **[Releases](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases)** 提供。当前为 **0.1.0 Beta 预发布**，完整实机验收仍在进行；使用前请阅读对应版本说明。

1. 从 Releases 下载 Windows 安装应用 ZIP，完整解压并保留同目录文件。
2. 备份现有数据；如启用 BitLocker / 设备加密，保存并确认恢复密钥可用，暂停保护后进入 BIOS / UEFI 关闭安全启动（Secure Boot）。安装后确认 Windows 正常启动，再恢复保护。
3. 为目标 GPT 磁盘准备至少 **64 GiB 连续未分配空间**，并为 Windows 中的系统准备工作空间预留至少 **45 GiB** 可用空间，建议 **64 GiB**。
4. 双击 **`SteamOSInstaller.exe`**，按向导选择安装位置、官方系统镜像及需要的适配组件。支持内置硬盘双系统安装；外部 SD / SSD 安装为 Beta。
5. 核对目标磁盘、分区方案与安装选项，可按需启用 rEFInd 启动菜单，确认后开始安装。
6. 安装完成后，按应用提示启动 SteamOS，并检查游戏模式、桌面、按键和插件。

系统镜像从 Valve 官方来源获取。首次使用陀螺仪需进行校准；Waydroid 的 Android 镜像需另行初始化。当前适配以 SteamOS 3.10 为基线，陀螺仪方案针对 BIOS 5.09。

安装包不含系统镜像，准备 SteamOS 3.10 及部分组件初始化需要联网。完整步骤见 [安装指南](windows-installer/docs/INSTALLATION_GUIDE.md)。

## 5. Roadmap

- [ ] G3E 开关核控制
- [x] 触屏友好安装器 UI / UX
- [x] 内置启动管理器：Windows / SteamOS 启动选择与默认启动项管理
- [ ] 免构建 64G 系统镜像及配套安装器

更多后续工作见 [Roadmap](ROADMAP.md)。

## 6. 许可证

Copyright © 2026 FlightDan and contributors.

除另有说明外，本仓库的原创代码与文档采用 **GNU Affero General Public License v3.0（`AGPL-3.0-only`）**，完整条款见 [LICENSE](LICENSE)。

第三方代码、组件、固件和系统镜像保留各自的版权与许可证。Opti2XMX 当前同样采用 `AGPL-3.0-only`，其使用的 Decky 模板保留原 BSD-3-Clause 声明。详见 [第三方声明](THIRD_PARTY_NOTICES.md)。

本项目为社区维护的非官方项目，与 Valve、Intel 或 ONEXPLAYER 无官方隶属关系；相关商标归各自权利人所有。

## 7. 致谢

感谢以下项目及其贡献者：

特别感谢 **HANA** 提供的原始设备适配项目 **[onexplayer3-steamos-setup](https://github.com/HHHHanasak1/onexplayer3-steamos-setup)**，以及提供设备、日志和实机反馈的测试者。

- **设备适配**：[InputPlumber](https://github.com/ShadowBlip/InputPlumber)、[Linux](https://kernel.org/)、[KDE / KWin](https://invent.kde.org/plasma/kwin)、[Gamescope](https://github.com/ValveSoftware/gamescope)、[SteamOS Manager](https://gitlab.steamos.cloud/holo/steamos-manager)、[MangoHud](https://github.com/flightlessmango/MangoHud)。
- **XeSS 支持**：[Intel XeSS](https://github.com/intel/xess)、[xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux)、[OptiScaler](https://github.com/optiscaler/OptiScaler) 及 [XeSS 配套运行环境](THIRD_PARTY_NOTICES.md)。
- **插件框架**：[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)。
- **Android 支持**：[Waydroid](https://github.com/waydroid/waydroid)（[SteamOS 集成](https://github.com/pjohno/steamos-waydroid-bundle)）。
- **双系统启动**：[rEFInd](https://www.rodsbooks.com/refind/)、[UsbXbox360Dxe](https://github.com/jlobue10/UsbXbox360Dxe)。

各第三方项目的来源、用途与许可范围详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
