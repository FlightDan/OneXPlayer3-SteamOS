# 本地正式发行准备工具

2026-10-16 已建立正式 Ed25519 发行身份并提供统一入口。此工具只生成密钥和本地发行产物，不创建 Release、不上传文件、不修改实机信任。

```powershell
./steamos-maintenance/release-maintenance.ps1 -Action status
./steamos-maintenance/release-maintenance.ps1 -Action init-key
./steamos-maintenance/release-maintenance.ps1 -Action preflight -Version 0.1.4 -OptiPlugin <最终插件ZIP>
./steamos-maintenance/release-maintenance.ps1 -Action prepare -Version 0.1.4 -OptiPlugin <最终插件ZIP> -OptiRuntime <已发布原始运行库>
```

入口自动优先使用本机 Codex 捆绑 Python；也可用 `-Python` 指定 Python 3.10+。密钥操作默认使用 Python cryptography，也可传入 OpenSSL。正式模块打包使用现有 OpenSSL 验签链，要求真实 OpenSSL 3.x 命令行。

本机已从 [Git for Windows v2.56.0.windows.2 官方便携包](https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.2) 提取 OpenSSL 3.5.9 及匹配 DLL/许可证，位于 `.release-work/toolchain/openssl/ucrt64/`，工具会自动发现。下载包大小和 SHA-256 已对照官方发布 API 校验，来源记录保存在 `.release-work/toolchain/openssl-origin.json`。未执行安装器或修改系统 PATH；此目录不进入源码导出或维护包。其他机器可用 `-OpenSsl` 或 `OXP3_OPENSSL` 指定真实 OpenSSL。

## 已建立的身份

- 公钥：`steamos-maintenance/trusted-public-key.pem`。
- 公钥 DER 的 SHA-256：`1a7805ce8d658c10f7fa3e04ec8bcd108a655f8ff0301373d23b8989c241b0af`。
- 私钥存储：工作区根目录 `.release-private/maintenance-ed25519/`，使用 Windows 当前用户 DPAPI 加密，访问仅限当前用户和 SYSTEM。
- `init-key` 重复运行会检查并复用同一身份，不轮换密钥。损坏、不完整、权限异常、密钥不符或签名中断遗留明文时明确拒绝继续。
- 签名时临时 PEM 位于受限密钥目录，正常完成或异常退出均删除；强制终止后的遗留会阻止下一次操作，需审计后处理。
- DPAPI 存储依赖当前 Windows 账户及用户配置；复制加密文件不等于可跨机器恢复的离线备份。

本环境沙箱用户配置无法调用 DPAPI。需在实际 Windows 用户上下文运行，不能因此覆盖、重建或移动现有正式身份。

## 准备与发布边界

`preflight` 只检查输入。`prepare` 在被 Git 忽略的 `.release-work/` 新建目录，依次生成当前载荷、校验 XMX 缓存与插件已发布描述、覆盖明确版本并构建签名模块发行。仅 `publisher-report.json` 中 `complete: true` 的产物可进入后续审查；`artifacts/release-plan.json` 给出目标仓库、Tag 和附件关系。

0.1.4 组件任务已完成，最终独立插件为 0.2.4（帧生成控件保留实验标记）。正式密钥初始化、状态复核及原生 OpenSSL 签名/验签/临时私钥清理自检成功。显式原始运行库覆盖只写入新建暂存目录，按最终 ZIP 描述校验，不覆盖旧缓存。README 已由用户确认；公开发布及实机升级按发行顺序执行。

维护渠道发布使用 `maintenance-v0.1.4`，标题为 `OXP3 SteamOS v0.1.4 — Maintenance Tools (Bash Installer)`，Windows 安装器保持 Latest。后续代理按 [AGENTS.md](../AGENTS.md) 审查并发布，不需要用户手工拼接命令。

## 验证

独立审查已完成。真实 Windows DPAPI、ACL、锁、错误状态、Ed25519 签名验证和临时明文清理的 17 项测试通过。维护工具全量回归 463 项完成（461 通过、2 项平台跳过）；审查修正后的发布输入检查 9 项、语言检查 7 项定向复测通过。补齐原生 OpenSSL 后，12 项真实加密打包回归通过。已在实机临时运行修复后的窗口，确认 KDE 中文翻译语言与英文区域格式并用时显示中文；截图验证不等同于正式工具升级。

最新发布前全量：Windows 491 项（481 通过、10 跳过）；隔离 Linux 491 项（476 通过、15 跳过）。详细边界见 [验证记录](../VALIDATION.md)。
