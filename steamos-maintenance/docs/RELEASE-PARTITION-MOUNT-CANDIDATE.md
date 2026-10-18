# KDE 分区自动挂载（未发布候选）

2026-10-19 后续修订见 [1.0.6+maintenance.3 候选](RELEASE-1.0.6-maintenance.3.md)：补充维护入口、FAT32、分区状态/过滤原因与 fstab 兼容修复。正式密钥已在正常 Windows 用户上下文确认 ready；下文密钥阻塞是历史结果。

2026-10-18：维护器增加 `partition-mount` 固定文件适配，使用安装器的同一份 GUI、后台及桌面入口源码。仅部署工具，不改用户 fstab 或实际挂载磁盘；用户在 KDE 中独立选择数据分区并授权持久化。与新装使用同一组件 ID 和默认选项；维护专用清单不再重复增加一份选项。

后台采用标准 pkexec 管理员认证；不提供免密 polkit 规则。恢复只恢复本组件部署文件，后期用户选择的 fstab 挂载需先在 GUI 取消。适用 NTFS/ntfs3、exFAT、ext4；当前槽保存配置。用户后续授权SSH/KDE/重启，已在OXP3 3.10 B槽完成私有loop ext4/exFAT真实挂载、重复启用、KDE原生Wayland窗口及一次重启后的按需挂载验证，原fstab及临时服务清理核验通过。NTFS、GUI管理员授权完整流程、A/B继承及签名维护升级仍未验收。

正式密钥、签名、组件完整目录、公开下载与实机升级仍遵守 AGENTS.md。此前 status/preflight 返回 `Cannot inspect publisher key permissions.`，没有生成或替换密钥，也没有发布资产。维护本地载荷已由既有 prepare_payload.py 刷新，资源覆盖完整；最终以`maintenance-payload-live-final`为准，5份部署源码与生成清单大小和哈希匹配。33项隔离Linux测试、24项准备/兼容性回归、1项fixture分片完整性检查通过。安装器携带的维护运行时35文件已刷新并通过源码一致性检查。完整交付核销与实机边界见 `windows-installer/docs/RELEASE_PARTITION_MOUNT_CANDIDATE.md`；独立试部署不代表完成签名维护器接管/升级。
