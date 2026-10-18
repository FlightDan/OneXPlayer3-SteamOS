# 1.0.5 更新说明

项目整合版本：1.0.5

## 更新内容

- 更新 SteamOS guest 集成复核：排序、快捷方式存在性与副本一致性、快捷方式标签及 KDE 语言偏好不再阻断安装。GTK 维护界面、Flathub 配置、Opti 运行库/编译器及控制组件 Python 依赖等可选探测按组件作用域执行；探测失败记录 `OXP_COMPONENT_WARNING` 并继续。
- 磁盘、槽位、挂载、启动配置、事务与回执、共享存储、权限、账户、驱动兼容性及 initramfs 等关键检查仍会阻断安装。I/O 错误、磁盘空间不足、设备断开、只读文件系统和权限错误仍按失败处理。
- 安装结果页不新增警告摘要。
- 组件基线为 Opti2XMX 0.2.4、OXP3 Light 0.1.0、Overlay r7，并沿用现有 maintenance.5 维护代码。

## 验证状态

用户报告已在本地测试基于 0.1.4 的非关键问题修复安装器。该测试针对本地候选，不代表正式 1.0.5 包或新版本的实机安装、升级及重启验收。1.0.5 已重新编译（0 警告、0 错误），现有 11 项发布 smoke 检查通过；重新生成的 101 个运行载荷文件与用户测试的候选一致。维护版本/发现的 36 项测试通过。尚未另行执行最终 1.0.5 实机安装、维护升级和重启；公开附件摘要与下载核对结果随 Release 记录。

## English

OXP3 SteamOS project release 1.0.5 updates guest integration verification. Plugin ordering, shortcut presence and copy consistency, shortcut labels, and KDE language preference no longer block installation. Optional, component-scoped probes for the GTK maintenance UI, Flathub configuration, Opti runtime/compiler, and controller Python dependencies emit `OXP_COMPONENT_WARNING` and allow installation to continue.

Critical checks for the target disk and slot, mounts, boot configuration, transactions and receipts, shared storage, permissions, accounts, driver compatibility, and initramfs remain blocking. I/O errors, low disk space, device disconnects, read-only filesystems, and permission errors remain failures. The result page adds no warning summary. The component baseline is Opti2XMX 0.2.4, OXP3 Light 0.1.0, Overlay r7, and the existing maintenance.5 implementation.

The user reports having tested the local non-critical-fix installer based on 0.1.4. That test covers a local candidate; it does not establish acceptance of the final 1.0.5 package or a live 1.0.5 install, upgrade, or reboot. The 1.0.5 application rebuild completed with no warnings or errors, all 11 existing release smoke checks passed, and 101 regenerated runtime payload files match the tested candidate. All 36 maintenance version/discovery tests passed. No separate live install, maintenance upgrade, or reboot of the final 1.0.5 artifacts is claimed; public artifact digests and download verification are recorded with the Release.