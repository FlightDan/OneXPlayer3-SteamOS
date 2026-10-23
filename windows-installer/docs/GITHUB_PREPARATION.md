# GitHub 上传准备

更新：2026-10-15。项目仓库位于 [FlightDan/OneXPlayer3-SteamOS](https://github.com/FlightDan/OneXPlayer3-SteamOS)；0.1.3 stable 是当前整合版，Windows x64 安装包以 Release 附件提供。此前的 **0.1.2 stable**、**0.1.1 stable**、**0.1.0 Beta** 及其 ZIP 保留为历史版本。stable 指本项目的整合版渠道，SteamOS 官方更新分支仍独立为 `stable`。共享挂载选择隐藏且功能仍不可用。0.1.3 安装器已修复 AnimationChanger 1.3.2 的更新器动画字体路径兼容问题；用户确认测试通过，隔离的官方更新器测试显示 SteamOS 标志和文字进度。更新可能下载数百 MB，请等待进度完成，进度仍在变化时不要强制关机。运行包编号以 `build-info.json` 为准。第三方运行时源码与许可材料仍须按实际分发范围核对。

## 拟上传目录

运行 `scripts/prepare-github-source.ps1` 会在 `windows-installer/dist/github-source-<时间>/` 生成新的源码快照。保留现有目录层级：

| 目录/文件 | 内容 |
| --- | --- |
| 根 README、ROADMAP、GIT_WORKSPACE | 公开项目说明、后续计划和构建工作区说明 |
| `.gitignore`、`.gitattributes` | 源码忽略与文本格式规则 |
| `windows-installer/app` | WPF、安装控制器、原生助手及验证源码；不含 bin/obj |
| `windows-installer/components` | 组件部署、选项、翻译、版本、rEFInd 与第三方署名材料 |
| `windows-installer/guest`、`scripts` | 虚拟机任务、准备/部署和开发脚本 |
| `windows-installer/docs` | 维护中的指南、截图与验收说明；不含内部设备排故 JSON |
| `windows-installer/licenses` | 已保存的第三方许可与分发清单 |

源码快照不是完整安装器。构建和运行仍依赖本地 .NET、QEMU、离线软件包及组件资源；完整运行包应以后单独作为发布附件准备。

## 保留在本地的内容

- 研究记录、历史路线图、设备地址/协调记录、其他独立仓库、`.git` 历史。
- `.g3e-fix-build`、临时传输配置、空白临时文本、验证用途 EXE。
- runtime、cache、work、output、logs、dist、bin、obj、node_modules 和 Python 缓存。
- SteamOS / Android 镜像、虚拟盘、ZIP、用户工作空间设置、私钥、环境变量文件与凭据。
- 内部排故 JSON 和原始设备日志。需要公开的测试结论整理为说明，不直接携带设备现场记录。
- `scripts/collect-desktop-runtime.py`：依赖本地设备地址、凭据文件和研究工具的资源采集脚本，保留在开发工作区；公共源码仍需另行准备相应运行载荷。

已有 Git 跟踪的内部文档不会因为补充 `.gitignore` 就自动取消跟踪，因此公开发布应使用白名单源码候选目录。不要直接把 开发工作区 整个目录拖入 GitHub；首次公开源码也不要携带未经审查的本地历史。

## 目录审查与验证边界

导出脚本记录文件路径、数量和字节数，不生成摘要。审查源码候选目录的相对 Markdown 链接、禁止携带的目录/扩展名、明显的密钥格式及超大文件；仅输出问题文件与行号，不输出疑似凭据内容。

本次源码上传采用白名单快照，在独立检出目录中追加提交，保留 GitHub 已有历史。检查文件清单、明显凭据格式、相对文档链接与超大文件后上传；不将本地开发仓库的历史推送到远程。项目原创内容许可证已经确定为 `AGPL-3.0-only`，见根目录 [LICENSE](../../LICENSE) 和 [第三方声明](../../THIRD_PARTY_NOTICES.md)。

0.1.3 新安装保持 `atomupd` 运行并指向必需的私有本地空更新源；恢复更新或执行官方 SteamOS 系统更新可能从 3.10 回滚至 3.8 并覆盖 Wi-Fi、手柄等适配。用户确认更新器字体路径修复测试通过：当前设备已核对为 B / 3.10 / build 20260924.1000 / kernel 7.2.4，隔离的精确官方更新器字体 A/B 测试使用完整离线资源并显示 SteamOS 标志和文字进度。针对本次修复的 Linux 5 项回归、修复夹具及独立审查通过；完整无人值守全新安装和当前挂载可用性未验收。构建编号应从最新 Release 附件的 `build-info.json` 读取，不将源码缓存 ZIP 当作改动载荷。第三方运行时源码与许可证仍需按实际分发范围核对。

1. 当前共享分区挂载不可用且选择入口隐藏。更新器进度字体修复的验证不代表完整无人值守全新安装、Steam 登录或所有硬件均已验收。
2. 实机安装和启动后的硬件、插件、重启、休眠及外部 SD / SSD 场景仍按各指南所列范围逐项验证。
3. 保留各第三方与原适配来源的许可材料，分别核对实际分发范围；不应将整包统一声明为 MIT 或 AGPL。
4. 含运行时的 ZIP 中 QEMU / Alpine / Decky / Waydroid 等源码与许可证材料仍须按实际分发内容核查；详见 [运行时清单](../licenses/README.md)。
5. 后续代码发布前重新导出源码快照并检查最新说明与目录。每个快照只包含导出当时的内容。

取消 xe `enable_dsb=0` 另列 [后续计划](../../ROADMAP.md)，当前仅登记，不改动安装默认配置。
