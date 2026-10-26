# OXP3 SteamOS 1.0.6 — LSFG-VK 可选组件

新增默认关闭、依赖 Decky Loader 的 `lsfg-vk` 选项，中英文界面显示官方插件版本 0.14.4、前置要求及后续操作。载荷固定官方 ZIP 为 5,322,847 字节、SHA-256 `a2187926dfb53e1813fa786d6e12a1d078638aa27153061389b755806e97338f`，保留全部 27 个上游文件及许可证；所含官方 LSFG-VK 2.0.0 离线资源 SHA-256 为 `08bdbdf373a111022df87dac7aa87e3b564bb841f961552e3ca85fea12b5aa74`。

用户先自行购买并安装 Steam Lossless Scaling，切换 `lsfg-vk` 分支，再在 Decky 插件中点击 Install LSFG-VK，由普通用户安装运行层。安装器不分发付费 DLL、不覆盖用户配置、不修改游戏启动项；维护恢复仅撤回托管插件代码，保留用户运行层、配置及游戏状态。

本构建携带同源维护工具及 maintenance.17 的恢复后重装修复。完整公开版本的源码、载荷生成、独立审查、真实 SteamOS Linux 新装/维护集成 22 项（0 跳过）、最终签名维护升级/恢复/重装/重启、ZIP 独立检查 18 项、打包后冒烟检查 15 项均已完成。重启后 Decky 显示 0.14.4，用户运行层 2.0.0 健康检查及归属权限通过，27 个插件文件符合官方哈希，50 个受保护文件保持一致。完整安装包已从公开入口匿名重新下载并通过大小、SHA-256、CRC、版本、便携启动入口与源码标识检查。

验收范围为组件集成和维护生命周期，未执行整盘 Windows 新装，未配置付费 DLL 或测试游戏补帧/性能。完整交付清单及恢复范围见 [maintenance.17 记录](../../steamos-maintenance/docs/RELEASE-1.0.6-maintenance.17.md)。

[Windows Release](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/v1.0.6%2Binstaller.20261027.031753)（Latest），构建 `20261027-031753`，源码 `fd9fd1d86d271431c47e4c93b41a0214de3f6572`；项目显示版本仍为 1.0.6。

附件 `oxp3-steamos-installer-1.0.6-20261027-031753.zip`：569,523,469 字节，SHA-256 `9a6bc851f246d13fd2bcf331983c4360019ec2a63ba81bd9ee295c5b998005d3`。

[维护 Release](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v1.0.6%2Bmaintenance.17) 已先行发布并通过最终产物实机升级验收。旧 maintenance.16 的恢复后重装问题由新修订解决，历史附件保留且未覆盖。
