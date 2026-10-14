# GitHub 上传准备

更新：2026-10-14。用户已授权把当前安装器源码上传到已有的 [FlightDan/OneXPlayer3-SteamOS](https://github.com/FlightDan/OneXPlayer3-SteamOS) 仓库。首次上传保持私有，改为公开需等待用户确认。完整流程测试已按用户要求停止，排故转入单独会话；之前的局部通过记录不能作为本轮完整安装通过的结论。

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

已有 Git 跟踪的内部文档不会因为补充 `.gitignore` 就自动取消跟踪，因此公开发布应使用白名单源码候选目录。不要直接把 `C:\steamosmod` 整个目录拖入 GitHub；首次公开源码也不要携带未经审查的本地历史。

## 目录审查和待完成条件

导出脚本记录文件路径、数量和字节数，不生成摘要。审查源码候选目录的相对 Markdown 链接、禁止携带的目录/扩展名、明显的密钥格式及超大文件；仅输出问题文件与行号，不输出疑似凭据内容。

本次源码上传采用白名单快照，在独立检出目录中追加提交，保留 GitHub 已有历史。检查文件清单、明显凭据格式、相对文档链接与超大文件后上传；不将本地开发仓库的历史推送到远程。项目原创内容许可证已经确定为 `AGPL-3.0-only`，见根目录 [LICENSE](../../LICENSE) 和 [第三方声明](../../THIRD_PARTY_NOTICES.md)。

正式安装包 Release 发布前仍需：

1. 在排故会话修复当前问题，重新完成完整虚拟机/虚拟盘流程。
2. 用户实机安装跑通，并记录 Windows/SteamOS 启动、主要硬件和插件结果。
3. 保留各第三方与原适配来源的许可材料，分别核对实际分发范围；不应将整包统一声明为 MIT 或 AGPL。
4. 若同时分发含运行时的 ZIP，补齐 QEMU / Alpine / Decky / Waydroid 等对应源码及许可证材料；详见 [运行时清单](../licenses/README.md)。
5. 排故后重新导出源码快照、检查最新说明和目录，再更新 GitHub 源码与对应 Release。每个快照只包含导出当时的内容。

取消 xe `enable_dsb=0` 另列 [后续计划](../../ROADMAP.md)，当前仅登记，不改动安装默认配置。
