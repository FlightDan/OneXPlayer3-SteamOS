# OXP3 SteamOS 1.0.6 — Windows 20261022-220437

修复 Opti2XMX 下载源在 Steam 原生下拉菜单卸载、重建面板后恢复 GitHub 的问题。普通安装/修复和高级版本安装保留当前插件会话选择，刷新、重开和失败重试继续使用所选源；重载插件恢复默认官方源。已有下载缓存继续复用，不宣称修复设备 DNS 或保证第三方镜像连通性。

显示版本 1.0.6；维护修订 1.0.6+maintenance.9；插件 0.2.8；Windows 构建 20261022-220437。正式执行源码为 e181a9055e1c94e8d758e2b9575f60fb5fc5109c（基于 m8 的 e7a5080），独立插件源码 56d7b987a8908edd430b4086ea6ff05df2939cfb。发布后的文档核销不改变这些已固定的构建源码或附件。

OptiScaler 版本、XMX 20261005 原始运行库及其他组件载荷不变。未公开动态功耗研究、核心算法、设备记录、凭据和私钥未进入公开 checkout 或成品。

| 项目 | 结果 |
| --- | --- |
| 1. 更新列表与记录 | 完成：本记录与对应 Release 一致，修复及验收边界如上。 |
| 2. 安装脚本、目录与载荷 | 完成：正式 CI ZIP 固定来源与 SHA-256、16 个成员及部署来源一致；定向重新生成 17 个 Opti 目标，其余 16 组件/138 载荷文件保留。完整插件同步检查通过，随包维护工具重新准备 40 文件。组件 ID、默认项、依赖、适用条件及中英文选项未变，无需修改 app 或新增维护选项；rEFInd 继续为独立操作。 |
| 3. 版本与标识 | 完成：1.0.6 / maintenance.9 / Opti 0.2.8 / Windows 20261022-220437；新 Tag 与新附件，保留历史引用。 |
| 4. 针对性验证 | 完成：实现、独立审查、类型检查、构建、前端原生菜单生命周期及 RPC 回归；新测试拒绝旧构建。正式 Opti CI 和掌机临时目录 174 项后端测试通过；8 项固定载荷/定向重建测试通过；主分支维护事务 CI 通过。Windows 重建 0 警告/0 错误，源码和成品目录各 15 项发布 smoke 通过；最终 ZIP 独立审查通过。 |
| 5. 维护器签名 Release | 完成：原正式 Ed25519 身份，publisher complete=true；32 目录项/31 可维护组件/14 分片覆盖完整，7+4 本次附件先核对上传再公开，维护不承担 Latest。 |
| 6. 公开下载与实机验收 | 完成：7 个当前维护附件和 15 个引用匿名重下验签、哈希、大小及完整离线 ZIP CRC 通过；API 和真实 Atom 回退发现 m9，修订排序通过。OP3 m8→m9 工具与插件限定升级、回退、重部署通过，16 个旧/新插件成员分别与正式包字节一致，保护的游戏状态/运行库配置不变。真实 Steam 高级菜单 ghfast、gh-proxy、官方源均跨面板重建保留；已恢复原界面。计划 restart_required=false，系统重启不适用；已定向重载插件并实测最终前端。最终维护状态无 pending。 |
| 7. 完整 Windows 包与 Release | 完成：同一执行源码刷新载荷与维护器、构建、目录烟测及完整包独立审查；受审查的 CI 从公开旧包重建同字节完整 ZIP 后上传，远端大小/摘要等于本地成品。维护门槛通过后公开并设为 Latest；公开最终完整 ZIP 再次匿名下载，SHA256SUMS、大小、哈希、CRC、build-info、源码提交及包内版本/维护文件核验通过。 |
| 8. README | 完成：根中英文与维护 README 仅同步必要插件版本及已有版本链接；独立插件 README 同样只更新版本，未重写其他文案。文档核销与已固定的执行构建分开提交。 |
| 9. 最终核销 | 完成：安装入口、最终载荷、维护签名发布、公开下载及限定升级验收、完整 Windows Latest、README 全链路核对。 |

普通安装入口的原生菜单生命周期与所传来源由夹具覆盖，未额外执行真实游戏安装。本轮不包含全新 Windows 写盘、游戏画面/性能、休眠或新硬件验收；已有 m8 未改动组件的验收边界继续保留。

Windows 完整 ZIP：555,684,389 字节，SHA-256 `d8bee8bad14f4cd136c814ebcaa3299fa59202b6cdc6d26ec9c52af0e055f4d4`。

完整维护离线 ZIP：260,797,344 字节，SHA-256 `3448cc6fabed63965ef27e64a4d120fc3e8c995e78c71ea7cf3031bcf13c2fac`。

Opti CI ZIP：79,911 字节，SHA-256 `63a25f4911edf9534c6fc8e600287d7b6427216b9da6cd940d98d48a2ed0d9e6`。

[Windows Latest](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/v1.0.6%2Binstaller.20261022.220437) · [Maintenance](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v1.0.6%2Bmaintenance.9) · [Opti2XMX](https://github.com/FlightDan/Opti2XMX/releases/tag/v0.2.8)

[Opti CI](https://github.com/FlightDan/Opti2XMX/actions/runs/39789900946) · [维护事务 CI](https://github.com/FlightDan/OneXPlayer3-SteamOS/actions/runs/39792318465) · [同字节完整包重建 CI](https://github.com/FlightDan/OneXPlayer3-SteamOS/actions/runs/39794229599)
