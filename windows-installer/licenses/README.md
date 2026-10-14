# 第三方运行时清单

Opti2XMX 运行资源保留 xess-xmx-linux 的 LICENSE / THIRD_PARTY.md、IGC/ocloc 随附材料及 Intel XeSS LICENSE。精确来源与版本在 cache/integration/sources/opti2xmx/PROVENANCE.json；仅用于当前本地开发交付，公开分发材料随全包继续核对。OptiScaler 游戏文件由插件按用户选择下载，不预装到任何游戏。

`runtime-inventory.json` 记录当前工具携带的二进制路径、字节数、来源和已知许可证材料，不生成或比较摘要。

此目录是本地开发交付清单。QEMU 的 Windows DLL、Alpine ISO/内核与离线包、.NET Desktop、Decky 发布二进制及 Waydroid 嵌套组件的对应源码和完整许可证材料尚未闭合；开发包没有作为正式安装器发布。

HDR 模板保留原项目的 MIT 许可和作者署名。插件 ZIP 和 Waydroid r2 包携带上游各自的材料，不能把整包统一标为 MIT。7-Zip 与 .NET 的随附许可另行保留。
aria2 1.37.0 的 Windows 二进制随附 COPYING、AUTHORS、上游源码归档和构建说明；静态依赖的对应源码与许可闭合仍列为公开分发前待办。

desync 1.0.4 Windows amd64 用于还原 Valve 官方 casync 根镜像，来源为 https://github.com/folbricht/desync/releases/tag/v1.0.4 。BSD-3-Clause 许可和上游 README 随 runtime/desync 保留。

BMI260 包装模块保留源码 SPDX GPL-2.0-only OR BSD-2-Clause；专用 InputPlumber 0.78.0 二进制来源为 onexplayer3-steamos-setup v1.6.1，补丁与 InputPlumber 许可保存在 cache/integration/sources/gyro。来源及适用范围见 docs/GYRO_INTEGRATION.md；公开分发的对应源码闭合仍需与全包一并核对。
