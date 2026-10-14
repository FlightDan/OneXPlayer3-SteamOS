# 致谢与第三方来源

本项目整合 Windows 安装助手与 ONEXPLAYER 3 设备适配。感谢上游维护者，也感谢提供设备、首次启动记录、安装日志和持续实机反馈的测试者。

## 原始设备适配

[onexplayer3-steamos-setup](https://github.com/HHHHanasak1/onexplayer3-steamos-setup) 提供原始安装指南及 Wi-Fi、休眠、显示、输入、音量、电量和陀螺仪等适配基础。本仓库保留的原许可署名为 **Copyright (c) 2026 HANA & Claude**，见 [HDR 上游 MIT 许可](../components/hdr/UPSTREAM_LICENSE)。本项目在这些工作之上集成、修正和验证安装流程；具体适用范围以各组件记录为准。

## 系统、驱动与桌面

| 项目／维护者 | 本项目使用或参考的工作 |
| --- | --- |
| Valve / SteamOS、Gamescope、SteamOS Manager | 官方系统与恢复镜像、A/B 引导、游戏模式合成及系统管理接口 |
| Linux 内核与 linux-firmware 维护者、Intel 及相关驱动作者 | 内核、xe 显示、NVMe、无线／蓝牙固件及设备支持；固件为 Linux 运行时文件 |
| InputPlumber 维护者 | 输入设备与虚拟控制器支持；专用 0.78.0 分支补丁来源见 [陀螺仪集成](GYRO_INTEGRATION.md) |
| KDE、Qt 及桌面依赖维护者 | Plasma 桌面、KWin、桌面显示与输入功能 |
| Waydroid 及相关 Android 项目维护者 | 可选 Android 宿主适配；Android 系统镜像另行获取 |

BE201 固件固定来源为 linux-firmware 提交 `2ab4ce216003ee2c2396c69e19455e4379b0e1f0`，下载脚本见 [prepare-be201-firmware.py](../scripts/prepare-be201-firmware.py)。安装包内 `cache/integration/sources/be201/provenance.json` 记录具体文件来源，同目录保留 `LICENCE.iwlwifi_firmware` 和 `LICENCE.ibt_firmware`。

## 启动菜单、插件与运行工具

| 项目 | 用途／来源记录 |
| --- | --- |
| rEFInd / Roderick W. Smith 及贡献者 | 可选双系统菜单；版本、原始二进制和主题来源见 [SOURCE.md](../components/refind/SOURCE.md) |
| UsbXbox360Dxe / chenx-dust、SkorionOS、jlobue10、EDK II 贡献者 | 启动阶段手柄转键盘输入；使用 jlobue10 v1.8.0，保留 BSD-2-Clause-Patent 许可，见 [来源说明](../components/refind/SOURCE.md#uefi-controller-input) |
| Decky Loader 及插件作者 | 可选插件框架和 SteamGridDB、ProtonDB Badges、TabMaster、CSS Loader、AutoFlatpaks、Deck Settings、HLTB for Deck、Animation Changer 等插件；署名与许可按各自归档保留 |
| Intel XeSS、IGC / ocloc、xess-xmx-linux、OptiScaler 及相关作者 | Opti2XMX 的可选运行资源、编译与按游戏管理；详见 [Opti2XMX 集成](OPTI2XMX_INTEGRATION.md) |
| QEMU、EDK II、Alpine Linux | 独立准备环境、离线工具与虚拟 UEFI 验证 |
| .NET、Python 及各依赖维护者 | Windows 安装界面与系统准备／适配脚本 |
| 7-Zip / Igor Pavlov、aria2、desync / Folbricht 及贡献者 | 压缩处理、镜像下载及官方 casync 系统还原 |
| Flathub、中科大开源软件镜像维护者 | 可选桌面应用商店来源与镜像服务 |

## 主题素材与许可

rEFInd 主题使用的 Steam 图形来源于 Simple Icons；Outfit 与 DM Mono 字体保留各自 SIL Open Font License，具体文件和来源见 [主题来源记录](../components/refind/SOURCE.md)。Steam 和 Windows 标识用于说明对应启动系统，不表示相关厂商为本项目背书。

致谢不替代许可证。各组件分别遵守其随附许可，原作者署名与许可文本继续保留；不能把整个安装包统一标为 MIT。运行时和对应源码材料的现有记录与未完成项见 [第三方运行时清单](../licenses/README.md) 及该目录的 `runtime-inventory.json`。当前版本为 0.1.1 正式发布，第三方运行时及对应源码材料仍按清单记录各自的许可和待核对项。
