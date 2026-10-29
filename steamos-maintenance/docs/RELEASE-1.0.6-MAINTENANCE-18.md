# 1.0.6+maintenance.18 — NTFS 挂载前检查

显示版本仍为 1.0.6。本修订将 `partition-mount` 的只读 NTFS 状态检查、固定静态修复工具和 systemd 挂载前依赖同步到维护器；与 Windows 新装入口部署相同资源。

准备流程对检查器、ntfsfix、许可证、完整对应源和 manifest 使用固定文件白名单，验证源码 pin、大小、SHA-256 与当前构建输入。组件恢复仍由文件事务管理，用户独立保存的 fstab 不改写；generator 自动识别旧规范配置，模板服务仅作为挂载依赖启动。

只有已确认 dirty、未休眠且未挂载的已选卷执行有限修复并复查。Windows 缓存日志、未知版本、元数据异常与工具缺失会阻止修复。不能把本修订描述成自动修复任意 NTFS 损坏或完整 chkdsk。

完整行为、测试结果与交付门槛见 [安装器交付记录](../../windows-installer/docs/RELEASE_1.0.6_NTFS_PREFLIGHT.md)。

Desktop HDR 缓存阻塞已解决：备份旧缓存后恢复 maintenance.17 已公开完整载荷（SHA-256 `0b70c2342b86f3d1c908e47d001037a01b76a81d2c5989a5bd2626048511bc58`）。16 项实际源输入、CI commit/run/artifact 和新的断网 SteamOS ABI 已核验；保留 EDID-only、475/700 trial 和实际呈现完成检查。未弱化校验或换钥。

正式密钥 status/preflight/prepare 已完成，publisher-report.complete=true。签名目录含 33 项、32 个支持组件、15 个分片，只有 NTFS 分片重建，其余 14 个公开引用精确保持。独立白名单源码审查及 Git/签名字节一致性检查通过；不包含未公开动态功耗研究。

maintenance.18 已公开。匿名重新下载 8 个附件及 16 个分片/原始引用，签名、哈希、大小、离线完整包、API/Atom 发现和修订排序均通过。完整离线 ZIP 为 277022480 字节，SHA-256 `17f561f34f6ddce9b20b0c5a991d4da50c372f2c1b57abcb0ecfd971a2de1c24`。历史 Tag/附件不覆盖，Windows 旧安装器继续承担 Latest。

安装器公开源码 15 项发布冒烟及维护缓存 42 文件、NTFS/HDR/LSFG/Opti/离线包/重启载荷检查通过。指定实机 SSH 当前超时：本修订尚未执行正式 .17→.18 升级或重启，Windows 完整包发布门槛仍关闭。设备恢复联网后继续，不用源码回归或私有 loop 测试替代实机验收。未执行整盘全新安装或物理屏幕画质验收。

[维护器 Release](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v1.0.6%2Bmaintenance.18)
