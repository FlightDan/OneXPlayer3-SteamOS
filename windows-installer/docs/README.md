# 安装助手文档索引

按 2026-10-14 当前代码维护。整合版为 **OXP3 SteamOS 0.1.1 stable**，默认底座为 **SteamOS 3.10 / build 20260924.1000**。stable 是项目渠道标签；完整全新安装与首次开箱配置尚未测试，自动跨版本适配尚未实现。先核对 [安装助手 README](../README.md) 中的包与源码差异，旧 ZIP 不会随文档更新。

## 使用与排错

| 文档 | 内容 |
| --- | --- |
| [安装与测试指南](INSTALLATION_GUIDE.md) | 当前两个镜像子页、延后重建、工作空间、容量与剩余 NTFS、七步流程和排错 |
| [致谢与第三方来源](ACKNOWLEDGEMENTS.md) | 原适配项目署名、系统／组件上游、主题素材与许可入口 |
| [镜像下载](DOWNLOADS.md) | ZIP / BZ2、HTTPS 直链、条款、暂停续传与下载记录 |
| [实际安装](PHYSICAL_INSTALLATION.md) | 系统来源、目标条件、容量扩展、写入保护和固件入口 |
| [进度及容量估算](INSTALLATION_PROGRESS.md) | 工作空间至少 45 GiB / 建议 64 GiB、阶段权重、两位小数与固定诊断编号 |
| [安装恢复](INSTALLATION_RECOVERY.md) | 工具自有 VHD 演练恢复；实盘中断边界 |
| [rEFInd 安装与管理](REFIND_OPTION.md) | 默认项、倒计时、安装位置、配置/卸载及冲突保护 |
| [整合版版本](VERSIONING.md) | 版本来源、构建编号、系统内版本文件和后续编号规则 |
| [0.1.1 发布说明](RELEASE_0.1.1.md) | stable 整合版更新、验证范围与已知限制（中英文） |
| [0.1.0 Beta 发布说明](RELEASE_0.1.0_BETA.md) | 历史 Beta 运行包及其验证范围 |

## 设备与组件

| 文档 | 内容 |
| --- | --- |
| [组件集成](COMPONENT_INTEGRATION.md) | 修复、Decky / 插件、语言与版本依赖 |
| [重启进入 Windows](WINDOWS_REBOOT.md) | Decky 按钮、桌面快捷方式、一次性启动与恢复 |
| [Opti2XMX](OPTI2XMX_INTEGRATION.md) | 安装集成、XMX / Opti 注入与版本管理 |
| [BMI260 陀螺仪](GYRO_INTEGRATION.md) | BIOS / 内核依赖、新装校准与恢复边界 |
| [HDR 组件](HDR_COMPONENT.md) | 独立配置、兼容性门禁与恢复 |
| [桌面应用商店镜像源](FLATHUB_MIRROR.md) | 可选中科大 Flathub 源、默认选择和恢复 |
| [首次启动分发](FIRSTBOOT_DISPATCH.md) | 专用资源预览/验证入口与正常集成安装的区别 |

## 实现与验收

| 文档 | 内容 |
| --- | --- |
| [当前实现状态](../IMPLEMENTATION_STATUS.md) | 当前能力、本地验证证据、交付范围与待实测项目 |
| [rEFInd 验收](REFIND_ACCEPTANCE.md) | 安装/恢复、主题、虚拟 UEFI 与 Windows EFI 探针边界 |
| [触屏界面](TOUCH_UI.md) | 当前布局、调试入口、容量与确认交互、自动检查边界 |
| [分区部署](PARTITION_DEPLOYMENT.md) | 准备镜像、原生写入、VHD 演练和实盘入口 |
| [Windows 介质助手](WINDOWS_MEDIA_HELPER.md) | 管理员助手协议与虚拟介质验证范围 |
| [源码工作区](../../GIT_WORKSPACE.md) | 构建依赖、目录、包与本地归档规则 |
| [GitHub 上传准备](GITHUB_PREPARATION.md) | 源码候选目录、排除内容、目录审查与发布前条件 |

## 本地归档

旧开发流水账、早期五步 UI 设计、磁盘启动修复记录、启动器选型研究、早期倒计时测试及本次已整合的更新说明，已移到仓库根目录下的 `archive/windows-installer-history/2026-10-14/`。原始相对目录结构保留；部分技术文档另保留整理前快照。

该目录位于 `windows-installer` 开发区之外，由根 `.gitignore` 忽略，不参与公开源码候选目录或新包打包。当前操作以这里的指南和 README 为准；后续工作见 [后续计划](../../ROADMAP.md)。
