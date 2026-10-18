# Windows 1.0.6 完整包与维护工具修订 4

完整构建为 `20261019-032821`，构建源码 `61766b4fa8db247d78ccccecc3402ee6548ff8ce`，整合版本仍为 1.0.6。

随附维护修订 1.0.6+maintenance.4：修复已有组件识别及筛选，启动按设置检查，体检入口移入修复页，同维护窗口复用管理员授权。新装及维护入口均包含 KDE 分区开机自动挂载工具；默认安装工具，实际保存分区配置须由用户选择。

同源构建 0 警告 0 错误，11 项 Windows 发布 smoke、载荷/公钥/哈希/ZIP 完整性检查通过。维护公开下载及实机仅核心升级已完成，43 个应用文件未变；授权客户端一次密码、一个 helper 复用三次只读操作并在关闭后退出。GTK 桌面密码弹窗次数未自动测量。

[完整 Windows Release](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/v1.0.6%2Binstaller.20261019.032821) 已公开并设为 Latest；全部 2 附件通过公开重新下载校验。ZIP 大小 550,668,134 字节，SHA-256 `db52a872a38a464b0bb5b4cd766719e1dd8a3d75a083c4c33fdac7c9d00a63cc`。

[完整离线维护工具包](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v1.0.6%2Bmaintenance.4) 包含双击 OXP3-Maintenance.desktop 入口，无需终端，支持触摸；保持整个解压文件夹在一起，KDE 首次可能要求确认执行。

载荷仅来自审计公开基线及本轮白名单，CPU 保持公开版本；未包含动态功耗研究代码。完整无人值守新装、分区工具最终 NTFS/真实重启挂载及实机全量恢复未作本轮通过声明。详细状态见维护项目对应 Release 记录。
