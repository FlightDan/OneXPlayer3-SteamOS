# OXP3 SteamOS 整合版版本

2026-10-14 起，整合版正式编号为 **OXP3 SteamOS 0.1.0 Beta**。

唯一版本来源是 `components/release.json`：机器识别值为 `0.1.0-beta`，界面显示为 `0.1.0 Beta`。这是本项目设备适配、组件部署和配套安装助手的整合版本；SteamOS 自身的版本独立记录，默认安装目标仍为 3.10 / build 20260924.1000。

安装助手从编译时嵌入的同一份文件显示版本。后续开发包使用 `oxp3-development-0.1.0-beta-YYYYMMDD-HHMMSS.zip` 或 `.tar` 命名，包根保存 `release.json` 和包含构建编号的 `build-info.json`；打包目录仍按构建时间区分。每次打包必须使用新的构建编号。

后续系统部署在 `/home/.oxp3-installer/integration/A/result.json` 和 `B/result.json` 中记录整合版 `release`、实际系统 `system` 和逐项组件结果。选择组件并部署运行库时，系统内也保存 `/usr/local/lib/oxp3-integration/release.json`。版本标记表示部署来源；实际启用及成功情况以组件结果为准。

镜像准备时，在用户主文件夹生成 `/home/deck/OXP3-SteamOS-Version.md`。文件只包含英文标题 `OXP3 SteamOS Version` 和整合版号 `0.1.0 Beta`。打开主文件夹即可找到；不创建桌面文件。内容从同一份 `release.json` 生成，文件属于 deck 用户，沿用共享 home 文件的备份和冲突保护。

已有测试包 `oxp3-development-20261014-011613.zip` / `oxp3-development-20261014-013814.zip`、此前生成的镜像和已经安装的设备不会自动获得该标记。整合版登记及本次文档整理未重打历史包，也未部署到设备；最新交付状态见 [README](../README.md)。

## 后续编号

- 修复问题、小幅配置或文案调整：`0.1.1 Beta`、`0.1.2 Beta`。
- 增加功能：`0.2.0 Beta`。
- 结束 Beta 并完成正式版验收后，再确定正式版本号。
- 插件、固件、内核和 SteamOS 底座保留各自版本，不能用整合版号替代兼容性检查。

发布变更时更新版本来源并重新构建安装助手。每个版本记录变更内容、适用底座和验证结果。组件补丁更新、在线检查更新及一键升级流程仍待实现；本次版本登记不代表这些能力已经可用。
