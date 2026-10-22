# 第三方声明 / Third-party notices

本项目使用、适配或集成以下项目。AGPL-3.0-only 仅适用于本仓库另无说明的原创内容，不替代第三方组件的许可证。致谢不代表获得额外的分发授权。

This project uses, adapts or integrates the projects below. AGPL-3.0-only applies only to original content in this repository unless otherwise noted; it does not replace third-party licenses. Acknowledgment does not grant additional redistribution rights.

## 设备与图形 / Device and graphics support

| 项目 / Project | 来源 / Source | 用途 / Role |
| --- | --- | --- |
| onexplayer3-steamos-setup · HANA & contributors | [HHHHanasak1/onexplayer3-steamos-setup](https://github.com/HHHHanasak1/onexplayer3-steamos-setup) | 上游安装与修复包、HDR 模板、输入和陀螺仪适配基础 / Upstream install/fix pack, HDR templates and input/gyro support |
| Linux · hid-oxp / oxpec / BMI260/BMI270 | [kernel.org](https://kernel.org/) | 内核、手柄驱动、风扇/充电接口与陀螺仪驱动 / Kernel, controller driver, fan/charging interfaces and gyro drivers |
| Jovian-Experiments Linux mirror | [Jovian-Experiments/linux](https://github.com/Jovian-Experiments/linux/tree/7.2.4-valve1) | 本地 oxpec 驱动源码获取来源，保留内核版权声明 / Source retrieval for the local oxpec driver, retaining kernel copyright notices |
| InputPlumber | [ShadowBlip/InputPlumber](https://github.com/ShadowBlip/InputPlumber) | 手柄、背键、按键映射与陀螺仪输入 / Controller, paddle, button and gyro input |
| KDE / KWin | [KDE KWin](https://invent.kde.org/plasma/kwin) | KDE 桌面与内屏 HDR 映射；构建基线为 Valve 对应版本源码 / KDE desktop and panel-specific HDR mapping, based on the corresponding Valve source package |
| Gamescope | [ValveSoftware/gamescope](https://github.com/ValveSoftware/gamescope) | 游戏模式显示、HDR 与刷新率适配 / Game Mode display, HDR and refresh-rate support |
| SteamOS Manager · Valve / Collabora / Igalia contributors | [SteamOS Manager](https://gitlab.steamos.cloud/holo/steamos-manager) | 原生 TDP 接口与状态修复 / Native TDP interfaces and state fixes |
| MangoHud / mangoapp | [flightlessmango/MangoHud](https://github.com/flightlessmango/MangoHud) | 性能覆盖层与遥测展示 / Performance overlay and telemetry |

上游修复包的 MIT 版权与许可声明保存在 [licenses/upstream-fixes-MIT.txt](licenses/upstream-fixes-MIT.txt)。InputPlumber 及内核派生组件继续适用其各自许可证；不得把它们统一改标为 AGPL。BMI260 包装模块源码保留 `GPL-2.0-only OR BSD-2-Clause` 标识。

The upstream fix pack's MIT notice is retained in [licenses/upstream-fixes-MIT.txt](licenses/upstream-fixes-MIT.txt). InputPlumber and kernel-derived components retain their own licenses and must not be uniformly relabeled AGPL. The BMI260 wrapper source retains its `GPL-2.0-only OR BSD-2-Clause` identifier.

## XeSS 与插件运行环境 / XeSS and plugin runtime

| 项目 / Project | 来源 / Source | 用途 / Role |
| --- | --- | --- |
| Opti2XMX · FlightDan and contributors | [FlightDan/Opti2XMX](https://github.com/FlightDan/Opti2XMX) | AGPL-3.0-only；逐游戏 XMX 与 OptiScaler 管理 / AGPL-3.0-only project for per-game XMX and OptiScaler management |
| OptiScaler | [optiscaler/OptiScaler](https://github.com/optiscaler/OptiScaler) | 用户选择后下载的游戏超分与帧生成适配组件 / Game upscaling and frame-generation adaptation, downloaded on user request |
| xess-xmx-linux | [HHHHanasak1/xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux) | Linux XeSS XMX 运行环境 / Linux XeSS XMX runtime |
| Mesa / ANV | [Mesa](https://gitlab.freedesktop.org/mesa/mesa) | Intel Vulkan 驱动及相关适配 / Intel Vulkan driver and related adaptations |
| Intel Graphics Compiler | [intel/intel-graphics-compiler](https://github.com/intel/intel-graphics-compiler) | Intel GPU 编译器 / Intel GPU compiler |
| Intel compute-runtime / ocloc | [intel/compute-runtime](https://github.com/intel/compute-runtime) | 离线编译与配套运行环境 / Offline compilation and companion runtime |
| Intel XeSS | [intel/xess](https://github.com/intel/xess) | SDK 与运行库；遵守 Intel 随附许可，非本项目 AGPL 覆盖的组件 / SDK and runtime libraries governed by Intel's included terms, outside this project's AGPL scope |
| Decky Loader | [SteamDeckHomebrew/decky-loader](https://github.com/SteamDeckHomebrew/decky-loader) | 游戏模式插件加载器 / Game Mode plugin loader |
| Decky plugin template / frontend APIs | [Plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template), [frontend library](https://github.com/SteamDeckHomebrew/decky-frontend-lib) | 插件框架与前端接口 / Plugin framework and frontend APIs |

Opti2XMX 当前的 AGPL-3.0-only 及 Decky 模板 BSD-3-Clause 声明保存在 [licenses/Opti2XMX-AGPL-BSD.txt](licenses/Opti2XMX-AGPL-BSD.txt)。Intel XeSS、运行库中的嵌套组件和驱动构建各自需要保留对应版本的授权与源码材料。

Opti2XMX's current AGPL-3.0-only and Decky template BSD-3-Clause notices are retained in [licenses/Opti2XMX-AGPL-BSD.txt](licenses/Opti2XMX-AGPL-BSD.txt). Intel XeSS, nested runtime components and driver builds require their own version-specific license and source materials.

## 集成的第三方 Decky 插件 / Integrated third-party Decky plugins

0.1.4 开发分支新增 **OXP3 Light**，灯光协议来源于 honjow / HHHHanasak1 的 HueSync
及 Antheas Kapenekakis 的 HHD。固定来源、原作者和完整许可随插件保存，见
[来源说明](components/light/THIRD_PARTY_NOTICES.md)、
[HueSync BSD 许可](components/light/LICENSE-HueSync) 与
[HHD LGPL 许可](components/light/LICENSE-HHD)。

Split-lock 修复参考 kas5852 的上游 PR #16 和 20261015 修复包，保留
Copyright (c) 2026 HANA & Claude 及完整
[MIT 许可](components/split-lock/UPSTREAM_LICENSE)。
这些组件的许可独立适用，不会因本项目的 AGPL 声明被替换。

以下来源依据本地集成归档的元数据与随附许可记录；版本为当前整合基线，发行包可能更新。

Sources below follow the metadata and notices in the locally integrated archives. Versions describe the current integration baseline and may change between releases.

| 插件 / Plugin | 版本 / Version | 来源 / Source | 用途 / Role |
| --- | --- | --- | --- |
| SteamGridDB | 1.8.1 | [SteamGridDB/decky-steamgriddb](https://github.com/SteamGridDB/decky-steamgriddb) | 游戏封面与素材 / Game artwork |
| ProtonDB Badges | 1.3.4 | [bschelst/protondb-decky](https://github.com/bschelst/protondb-decky) | Proton 兼容性徽章 / Proton compatibility badges |
| TabMaster | 2.15.1+oxp3.1 (local patch of 2.15.1) | [Tormak9970/TabMaster](https://github.com/Tormak9970/TabMaster) | 游戏库标签管理与缺失成就缓存兼容 / Library tabs with absent achievement-cache compatibility |
| CSS Loader | 2.1.2 | [suchmememanyskill/SDH-CssLoader](https://github.com/suchmememanyskill/SDH-CssLoader) | Steam 界面主题 / Steam UI themes |
| AutoFlatpaks | 1.6.8+oxp3.1 | [jurassicplayer/decky-autoflatpaks](https://github.com/jurassicplayer/decky-autoflatpaks) | Flatpak 更新管理 / Flatpak update management |
| Deck Settings | 1.2.6 | [DeckSettings/decky-game-settings](https://github.com/DeckSettings/decky-game-settings) | 社区游戏配置 / Community game settings |
| HLTB for Deck | 2.0.12 | [morwy/hltb-for-deck](https://github.com/morwy/hltb-for-deck) | 游戏时长信息 / Game completion times |
| Animation Changer | 1.3.2 | [TheLogicMaster/SDH-AnimationChanger](https://github.com/TheLogicMaster/SDH-AnimationChanger) | 启动与休眠动画管理 / Boot and suspend animations |

TabMaster `2.15.1+oxp3.1` is built locally from the official Decky store 2.15.1 archive. Its TypeScript patch, unified diffs, and build notes are included in [the compatibility patch source](components/tabmaster-compat/README.txt).

AutoFlatpaks `1.6.8+oxp3.1` retains its upstream BSD-3-Clause license and defers polling until Steam exposes a complete battery state. The guarded poll source, bundle diff and reproducible builder accompany the [compatibility patch](components/autoflatpaks-compat/README.txt).

## Android / Android support

- [Waydroid](https://github.com/waydroid/waydroid)：Android 容器运行环境 / Android container runtime.
- [pjohno/steamos-waydroid-bundle](https://github.com/pjohno/steamos-waydroid-bundle)：SteamOS 集成基础与配套资源 / SteamOS integration and companion resources.
- Android 系统镜像及 Google 应用不因本仓库的 AGPL 声明获得额外授权；它们各自的许可独立适用。/ Android system images and Google apps receive no additional rights from this repository's AGPL declaration and remain governed by their own terms.

## 安装应用基础 / Installer foundations

| 项目 / Project | 来源 / Source | 用途 / Role |
| --- | --- | --- |
| .NET / Windows Desktop | [.NET runtime](https://github.com/dotnet/runtime), [WPF](https://github.com/dotnet/wpf) | Windows 安装应用运行环境 / Windows installer runtime |
| QEMU | [qemu.org](https://www.qemu.org/), [Windows builds](https://qemu.weilnetz.de/w64/) | 独立虚拟系统准备与启动验证 / Isolated system preparation and boot validation |
| EDK II | [tianocore/edk2](https://github.com/tianocore/edk2) | 虚拟 UEFI 固件 / Virtual UEFI firmware |
| Alpine Linux | [alpinelinux.org](https://alpinelinux.org/) | 安装准备环境 / Installation preparation environment |
| 7-Zip | [7-zip.org](https://www.7-zip.org/) | 归档解压 / Archive extraction |
| aria2 | [aria2/aria2](https://github.com/aria2/aria2) | 下载与续传 / Downloads and resuming |
| desync | [folbricht/desync](https://github.com/folbricht/desync) | 还原官方 casync 根系统 / Reconstructing official casync root images |
| kmscon | [Aetf/kmscon](https://github.com/Aetf/kmscon) | 控制台支持 / Console support |
| libtsm | [Aetf/libtsm](https://github.com/Aetf/libtsm) | 终端状态机 / Terminal state machine |

这些项目及二进制依赖按各自许可证分发。正式发行包应包含其需要的许可声明、对应源码或许可允许的源码提供方式；本清单不代表所有二进制分发材料已经核对完成。

These projects and their binary dependencies are distributed under their own licenses. A formal release must include required notices and corresponding source, or another source-delivery method permitted by the applicable license. This list does not indicate that all binary redistribution materials have already been finalized.

## SteamOS 与商标 / SteamOS and trademarks

SteamOS、Steam Client 及其系统包由 Valve 和其他权利人提供，适用各自许可。系统镜像由用户从官方来源获取，不由本仓库的 AGPL 声明重新授权。参考 [Valve 官方镜像条款](https://store.steampowered.com/steamos/download/?l=english&ver=steamdeck)。

SteamOS, Steam Client and system packages are supplied by Valve and other rights holders under their own terms. Users obtain system images from official sources; this repository's AGPL declaration does not relicense them. See [Valve's official image terms](https://store.steampowered.com/steamos/download/?l=english&ver=steamdeck).

本项目与上述项目及厂商无官方隶属关系。商标、名称与标识归各自权利人所有。

This project is not officially affiliated with the projects or vendors above. Trademarks, names and logos belong to their respective owners.
