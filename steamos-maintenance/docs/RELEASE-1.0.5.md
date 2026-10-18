# SteamOS Maintenance 1.0.5

## 更新内容

新增稳定版 1.0.5 发布记录，供维护入口进行所需版本发现。维护引擎、组件实现及载荷沿用 `0.1.4+maintenance.5`，本次没有更改维护执行逻辑或组件载荷。

本版本与 Windows 安装器 1.0.5 配套；安装器中的非关键 guest 复核问题修复详见 [Windows 安装器 1.0.5 更新说明](../../windows-installer/docs/RELEASE_1.0.5.md)。

## 验证状态

用户报告的本地测试对象是基于 0.1.4 的 Windows 非关键问题修复安装器，不是维护器 1.0.5。最终维护包已重新准备并以原正式密钥签名；完整目录覆盖 30 个组件，12 个分片引用与 maintenance.5 一致，28 个维护 Python 模块未变。桌面文件和许可证的行尾规范化改变了部分组件 revision，维护界面可能提示更新。维护版本发现的 36 项测试通过。公开下载、签名和附件哈希结果随 Release 记录；未另行执行 1.0.5 实机升级及重启。

## English

This release adds stable version 1.0.5 metadata for required-version discovery by the maintenance entry point. The maintenance engine, component implementation, and payload are carried forward from `0.1.4+maintenance.5`; maintenance execution logic and component payloads are unchanged.

This release accompanies Windows Installer 1.0.5. Its non-critical guest verification fix is described in the [Windows Installer 1.0.5 notes](../../windows-installer/docs/RELEASE_1.0.5.md).

The user-reported local test was for the Windows non-critical-fix installer based on 0.1.4, not Maintenance 1.0.5. The final package was rebuilt and signed with the existing production key. The complete catalog covers 30 components, retains all 12 package references from maintenance.5, and preserves all 28 maintenance Python modules. Line-ending normalization in desktop and license files changes some component revisions and may trigger update indications. All 36 version/discovery tests passed. Public-download, signature, and hash results are recorded with the Release; no separate live 1.0.5 upgrade or reboot is claimed.