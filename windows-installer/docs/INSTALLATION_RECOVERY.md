# 原生 EXE 安装恢复

主界面仍为 Windows WPF。首页“继续上次演练”和结果页“复查并继续”仅在任务带有新版本部署记录、源镜像与所有权记录，并且未被其他安装窗口占用时出现。旧任务记录不会被自动升级为成功或凭空补齐所有权。

当前代码已开放实盘安装，但本页的自动恢复仍只用于工具自有 VHD 演练。实盘停止或中断请保留任务目录、`physical-state.json`、GPT 备份与导出日志，不自动续写、回滚或删除新增分区。操作见 [安装指南](INSTALLATION_GUIDE.md)。

下文 `work` 指当前所选工作空间，默认是工具目录下的 `work`；切换工作目录不会搬移任务，查看或恢复旧演练时先切回原目录。

## 恢复规则

- 目标只允许 work 内由本工具创建的 VHD，不接收盘号或物理路径。新建时落盘保存 VHD 原生 GUID、容量和 Windows 文件标识；恢复拒绝同名替换、复制品、硬链接、路径重定向、缺失记录、差分盘或外部已挂载的盘。
- 整个 VHD 生命周期和安装会话分别持有独占锁。进程退出释放句柄。日志使用 schema 2，绑定源身份、目标身份、布局与安装模式，保留每次恢复前的记录。
- 已完成列表必须是八个系统角色的连续前缀。完整目标 GPT 必须已存在且与准备方案一致。早于完整分区布局形成的中断不自动修复或重新分区。
- 先逐字节复查全部已完成分区；任何一段不同都先停止，不续写后续分区。对未完成分区从头重新写入并读回，不相信旧字节计数代表已刷盘。这里没有引入额外哈希或指纹。
- 如果八个分区已完成，只复查内容，不重新复制。之后可重新进行独立 UEFI 启动验证。分区日志始终不冒充主机启动就绪。
- 新的管理员助手任务使用独立 nonce 与日志目录，恢复只开放 resume-owned-vhd-only 范围。原有助手记录不可复用覆盖。取消沿用事件通知、刷盘、释放卷锁和卸载 VHD 的流程。
- 原始准备阶段还没有可恢复目标时，继续使用新任务重试。电源突然中断后留下的锁、GPT 损坏、源镜像变化和受损的已完成分区均停止处理，不声称能自动撤销已有数据。

## 开发机验证

scripts/test-installation-recovery.ps1 -Mode compact 使用 Windows 原生 512 MiB VHD：写入进程在首个分区完成后直接退出，不执行应用 finally 清理；另一进程重新打开目标。内置共存、外部完整系统、部分未记录内容重新写入、完成后仅复查、损坏/源变化/模式不符/前缀错序/旧日志/目标身份不符/同名复制替换/缺失所有权记录均有独立检查。

-Mode internal|external -SourcePath <work 中 80 GiB prepared.img> 生成新的真实 SteamOS VHD 中断夹具，然后通过原生向导恢复及独立 UEFI 虚拟机启动。测试进程突然退出不等同于主机真正掉电。

已有验证记录见 logs/installation-recovery-20261013.json。普通用户交互 UAC、活动桌面触控、任意断电、主机固件入口和物理 SD/SSD/内置硬盘恢复仍需另行验证。当前实盘实现与限制见 [实际安装](PHYSICAL_INSTALLATION.md)。

## Windows API 依据

原生结构与标识使用 Microsoft 文档中的 [OpenVirtualDisk 参数](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/ns-virtdisk-open_virtual_disk_parameters) 和 [GetVirtualDiskInformation 信息类型](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/ne-virtdisk-get_virtual_disk_info_version)。VHD GUID 可随文件复制，因此还绑定 Windows 文件 ID，不能仅凭 GUID 决定续写。
