# 1.0.6+maintenance.18 — NTFS 挂载前检查候选

显示版本仍为 1.0.6。本修订将 `partition-mount` 的只读 NTFS 状态检查、固定静态修复工具和 systemd 挂载前依赖同步到维护器；与 Windows 新装入口部署相同资源。

准备流程对检查器、ntfsfix、许可证、完整对应源和 manifest 使用固定文件白名单，验证源码 pin、大小、SHA-256 与当前构建输入。组件恢复仍由文件事务管理，用户独立保存的 fstab 不改写；generator 自动识别旧规范配置，模板服务仅作为挂载依赖启动。

只有已确认 dirty、未休眠且未挂载的已选卷执行有限修复并复查。Windows 缓存日志、未知版本、元数据异常与工具缺失会阻止修复。不能把本修订描述成自动修复任意 NTFS 损坏或完整 chkdsk。

完整行为、测试结果与交付门槛见 [安装器候选记录](../../windows-installer/docs/RELEASE_1.0.6_NTFS_PREFLIGHT.md)。签名产物、公开下载和实机升级验收未完成前保持候选状态，不覆盖历史 Release 附件。

当前最终状态：维护单组件准备与最终分发清理后的 21 文件逐字节一致；准备/适配/策略测试 74 项中 72 项通过、2 项平台跳过；随 Windows 安装器携带的维护工具 39 文件重准备并校验通过。正式密钥 status 和 preflight 已通过；全量 prepare 被既有 Desktop-HDR 缓存缺少 EDID-only 标记拒绝，publisher-report.complete=false。尚未生成可发布的完整签名目录或执行公开下载、升级和重启验收。

2026-10-29 后续发布准备：根工作区旧 HDR 缓存已备份后恢复正式 maintenance.17 完整载荷（SHA-256 `0b70c2342b86f3d1c908e47d001037a01b76a81d2c5989a5bd2626048511bc58`）。16 项实际源输入、CI commit/run/artifact 及新的断网 SteamOS ABI 已核验；保留实际呈现完成检查。独立公共源码增量/研究排除审查通过，完整维护资源目录无缺项；正式密钥 status/preflight ready。后续签名、公开下载与设备验收按同一修订继续，原阻塞记录保留为历史，不代表当前仍被 HDR 校验拒绝。
