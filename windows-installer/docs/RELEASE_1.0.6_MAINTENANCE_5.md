# Windows 1.0.6 完整包与维护工具修订 5

本包整合正式维护修订 1.0.6+maintenance.5：系统检查为左侧独立导航入口，修复页顶栏不再放体检按钮，概览分区挂载工具下的重复说明已移除。中英文同步。

维护公开 Release 的签名核心、32 项目录及全部 14 个复用组件包已经核对。实际掌机通过原 maintenance.4 客户端自行从 GitHub 发现并下载新版，旧版验证器完成仅核心升级至 maintenance.5；组件选择及 33 个应用文件哈希不变，无需重启。原生 GTK 中英文导航、小窗口布局、系统检查和报告导出通过验证。

37 个维护运行文件及 manifest 已从最终源码重新生成并通过 Python/PowerShell 一致性检查。Windows 应用源文件 93 项与此前正式 1.0.6 相同，沿用哈希已核对的相同应用程序与 480 文件运行环境；本轮未重新编译该未改动的 Windows 应用。打包前 10 项发布 smoke 通过，发行包使用新时间戳和当前审计源码 SourceCommit，整合显示版本仍为 1.0.6。具体构建标识见包内 build-info.json，最终附件摘要见对应 GitHub Release。

完整离线维护包包含 31 个可维护组件及依赖和桌面双击入口，也已提供独立 ZIP。Opti 可选 XMX 运行库包含在完整包中；Waydroid 的 Android 镜像初始化仍需另行完成。

正式签名身份保持原值，CPU 维持公开基线；本包不含动态功耗研究代码、设备记录、凭据或私钥。本轮未进行完整无人值守新装、实际分区挂载或实机全量恢复测试；GTK 图形密码弹窗次数未自动测量，授权复用由实际 Client 和临时终端认证代理验证。

发布记录：新构建 20261019-151459 已公开并设为 Latest，2 个附件通过公开重新下载校验。Windows ZIP 为 550,669,864 字节，SHA-256 e44661979a5de4e3f255da33db1bcfe89321bbd23ef5b75ad4d5d641851ce43d。SourceCommit 为 e9e55c2a95c11740adf2de8383138dcfc9b47bc1。11 项发布检查包括 10 项功能检查及版本/便携启动器绑定检查。

https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/v1.0.6%2Binstaller.20261019.151459
