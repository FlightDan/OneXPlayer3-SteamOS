# SteamOS KDE 分区自动挂载（未发布候选）

2026-10-19 候选更新：维护概览新增“分区挂载”入口，也可在 KDE 普通用户终端运行 `oxp3-maintenance.sh partition-mount`。挂载窗口显示“未挂载/已挂载”及不可选原因；新增 FAT32/vfat 普通分区（包括常见 MBR SD 卡），修复 fstab 省略可选字段时被拒绝的问题。Windows C/D 在 Linux 没有对应盘符，请按卷标、容量和 UUID 选择。新功能、验证与发布边界以 `RELEASE_1.0.6_MAINTENANCE_3.md` 为准；下方 10 月 18 日实机结果属于旧候选。

2026-10-18 新增。适用于具有 KDE、kdialog、polkit、systemd、util-linux 和非 root `deck` 用户的 SteamOS。用户随后明确授权 SSH、切 KDE 与重启；已在 OXP3 / SteamOS 3.10 的当前 B 槽验证 GUI、私有 loop 的 ext4/exFAT 实际挂载、重复启用和一次重启后的按需挂载。测试配置已清理，工具保留安装。NTFS、其他机型/版本、切槽及签名维护升级尚未验收。

## 使用入口

安装器和维护器中的 `partition-mount` 默认选中，**只安装工具，不选择、挂载或修改任何磁盘**。KDE 桌面和应用菜单中的“SteamOS 分区自动挂载”提供启用、查看、取消三个操作。读取状态无需提权；保存配置时使用标准 pkexec 管理员认证，不安装免密授权规则。

分区列表显示设备、卷标、容量、文件系统和 UUID。当前支持 NTFS（内核 ntfs3）、exFAT、FAT32/vfat、ext4 普通数据分区；不支持 Btrfs 多设备、加密卷、RAID、整盘文件系统和其他格式。已识别的系统、EFI、保留、恢复（包括 RecoveryImages 前缀卷标）、只读分区，以及重复 UUID 和被其他系统路径使用的分区不提供选择。无系统标识且未挂载的其他 Linux 系统盘不能仅凭元数据完全识别，用户仍须核对用途。已有非本工具 fstab 项发生冲突时拒绝覆盖。

确认后写入当前系统槽 `/etc/fstab` 的独立标记块，目标固定为 `/var/mnt/oxp3-volumes/<文件系统UUID>`。下一次启动会建立 systemd 按需挂载，访问该目录时挂载；配置包含 `nofail`、设备和挂载超时。该配置同样可用于当前系统槽的游戏模式，但不自动注册 Steam 库。

本次保存后会尝试立即挂载并核对 UUID、文件系统、实际目标。若 Dolphin 已把它挂在 `/run/media/deck/…`，保留当前挂载，下次重启使用新路径。界面会分别报告“配置已保存”和“本次已挂载”；失败时保留已保存配置并显示错误。NTFS 的 Windows 休眠、脏卷或缺少驱动会导致挂载失败；不使用 `force`、不删除休眠文件。应在 Windows 完整关机后使用共享盘。

ext4 采用盘内原有的用户和权限，不自动递归改属主；NTFS/exFAT/FAT32 映射到 deck 用户。所有格式均使用 `nosuid,nodev`，允许执行以便运行普通数据盘内容。是否能用于特定 Proton 游戏需另外验证。

## 取消与恢复

“取消自动挂载”只删除本工具管理的对应行，不删除文件、不格式化，也不强行卸载正在使用的分区；现有挂载和已启动的按需挂载保留到重启。立即拔盘前仍须使用 Dolphin 安全卸载。断开的盘也可以从已保存清单取消。

每次配置实际变化前，原 fstab 原子备份到 `/etc/fstab.oxp3-partition-mount.bak`（root、0600）；该文件只保存**最近一次修改前**的快照，不是无限历史记录。写入使用同目录临时文件、fsync 和原子替换；独立锁串行化本工具操作，并在写入前复核 fstab 未改变。其他管理员程序不使用本工具锁时仍应避免并发编辑。

已管理块发生手工修改、存在不安全目录/链接、目标有待覆盖数据或发现自定义 systemd unit 时拒绝继续。人工恢复备份前应比较当前 fstab，防止覆盖备份以后新增的其他配置。

安装器/维护器的组件恢复只撤销安装时的工具文件，不撤销用户日后在 GUI 中选择的独立挂载配置。移除工具前先在 GUI 取消所需挂载。

## SteamOS A/B 边界

程序保存在 root 拥有的共享 `/home/.oxp3-partition-mount/`，两个槽均可保留入口。**fstab 属于当前系统槽**：重启同一槽会保留，切槽、重新安装或官方更新后的另一槽不保证继承；需要在对应槽再次确认。工具不挂载或改写未运行的系统槽，不把当前槽测试当作 A/B 迁移验证。

## 本地验证

Windows 可运行便携解析、过滤与 GUI 授权响应测试；Linux 文件生命周期测试必须在独立 root 测试环境运行。项目已有 QEMU 提供无网络、只有私有文件盘的验证入口：

```powershell
& '<bundled-python>' -B -m unittest -v test_partition_mount.py test_partition_mount_integration.py
& '<bundled-node>' windows-installer/scripts/run-guest.mjs partition-mount-tests
```

源码入口为 `components/partition-mount/`；安装适配为 `components/partition_mount.py`；维护适配为 `oxp3_maintenance/components.py`。具体结果和发布门槛记录在 `RELEASE_PARTITION_MOUNT_CANDIDATE.md`。

实现参考：[systemd.mount 的 fstab、automount 与超时说明](https://www.freedesktop.org/software/systemd/man/latest/systemd.mount.html)、[NTFS3 内核挂载参数](https://www.kernel.org/doc/html/latest/filesystems/ntfs3.html)。
