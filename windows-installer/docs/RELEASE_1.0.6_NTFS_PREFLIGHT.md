# 1.0.6 NTFS 挂载前检查与有限修复（2026-10-29）

本次补齐 KDE 分区自动挂载的启动前检查。项目显示版本保持 1.0.6，维护修订为 `1.0.6+maintenance.18`。正式维护工具已公开并通过匿名下载验证；实机升级、重启和对应 Windows 完整包仍待设备恢复联网后继续。

## 实际行为

- 新装和维护部署同一组源码、systemd generator、挂载前 oneshot 服务、静态 musl x86_64 检查器与 ntfsfix。固定上游 ntfs-3g/ntfsprogs 2026.2.25，包含完整对应源码、构建脚本、GPL 与 musl 版权声明。目标镜像额外要求 `blkid`；不在线安装系统软件包。
- generator 只读取工具原有的规范 v1 fstab 标记块，给其中的 NTFS `.mount` 添加 `Requires` 和 `After`。已有配置在下次启动或 daemon-reload 时同样生效；不改写 fstab、不添加自动卸载操作、不把预检依赖放到 `.automount`。
- 检查器使用 `RDONLY|FORENSIC`，显式检查 NTFS 版本、Windows 休眠文件及 `$LogFile` 缓存/恢复状态。Windows 缓存元数据、休眠卷和无法确认的元数据错误都会阻止修复。
- 服务只处理当前受管 fstab 明确选择的 UUID，检查块设备、NTFS 类型和未挂载状态。仅明确 dirty 且未休眠的卷允许执行一次 `ntfsfix --clear-dirty`；随后执行 `--no-action`、再次核对身份和只读状态，确认 clean 才放行挂载。
- `ntfsfix` 属于有限元数据修复，可修改元数据及日志，不能代替 Windows `chkdsk`。MFT/MFTMirr 不一致等无法读取的状态归为 unknown，不从检查失败推断 dirty，不自动尝试修复此类未知损坏。
- GUI 的 NTFS 立即挂载与开机按需挂载使用相同服务；挂载前确认文字说明有限修复。GUI 只接受本工具生成的唯一依赖 drop-in，并等待预检和挂载结束；服务拒绝原因从本次时间窗口的日志返回。

## 范围

组件 ID `partition-mount`、默认选择与组件依赖保持不变，安装选项中英文名称及组件目录已同步。独立的 `shared-storage`/Steam 库注册功能不属于本次挂载路径，未迁移该功能的 fstab 布局。

安装和维护事务仅安装/恢复工具、generator 与模板服务；用户保存的 fstab 不纳入事务。模板服务按挂载依赖启动，无须 enable。恢复工具后原有挂载配置保留，NTFS 仍由内核执行其普通挂载检查。A/B 槽分别部署各自的 generator 和模板服务，共享的工具源码仍在 root 拥有的 `/home/.oxp3-partition-mount`。

## 准备与验证入口

```powershell
& '<bundled-python>' -B windows-installer/scripts/prepare-ntfs-tools.py --offline
& '<bundled-python>' -B windows-installer/scripts/prepare-integration.py --partition-mount-only
./windows-installer/scripts/check-ntfs-tools.ps1
& '<bundled-node>' windows-installer/scripts/run-guest.mjs partition-mount-tests
```

`prepare-ntfs-tools.py` 每次构建使用固定源码/编译依赖和独立离线 VM；`--check` 仅验证已有构建，不能冒充重建。`prepare-integration.py --partition-mount-only` 仅刷新本组件的最终工具及 source-manifest，保留其他组件记录。公开完整安装包构建另会强制检查当前工具、对应源和受影响源码清单，拒绝旧缓存。

## 交付核销与最终验证

| 项目 | 状态与证据 |
| --- | --- |
| 安装/维护入口及选项同步 | 完成：两端相同固定资源与权限；维护准备专用白名单，不扩大通用二进制扫描 |
| 源码测试与独立审查 | 完成：最终 Linux 67 项全部通过；维护准备/适配/策略 74 项中 72 项通过、2 项既有平台跳过；独立审查提出的日志缓存、未知版本、等待时间、首次重试和路径转义问题均已修正 |
| 工具最终重建与只读镜像验证 | 完成：固定输入离线重建，ELF 无动态加载器/动态依赖；8 类镜像前后 SHA-256 相同，strace 无读写打开；额外未知版本镜像拒绝且未变更；最终 `--check` 通过 |
| Windows 应用构建 | 完成：0 警告、0 错误；不代表 Linux 新装验收 |
| 新装/维护资源与事务验证 | 完成针对性验证：两端实际源码/工具映射，维护单组件准备 21 文件完整、最终分发清理后仍逐字节一致；隔离 Linux 8 项维护入口/适配测试通过。完整系统新装/正式维护升级未验收 |
| 私有 loop / systemd 实机验证 | 完成：指定 SteamOS 3.10 / 7.2.4 设备，仅用全新 64 MiB 文件和 loop，挂载依赖触发 dirty→修复→ntfs3 rw；再挂载不重复修复，内容保留，已挂载检查拒绝。生产模板通过 systemd-analyze verify；临时实例使用实际 loop device 依赖和私有配置/工具路径，测试后临时单元、挂载和 loop 已清理。未重启设备、未操作用户 NTFS 卷 |
| 正式签名与完整维护 Release | 完成：恢复 maintenance.17 正式 HDR 完整载荷，强 EDID-only/呈现完成标记、源输入/CI 来源和离线 SteamOS ABI 通过；正式密钥重新 status/preflight/prepare，publisher-report.complete=true。签名目录覆盖 33 项、32 个支持组件和 15 分片；只重建 NTFS 分片，其余 14 个引用逐字节保留。maintenance.18 已公开，维护 Release 不抢占 Latest |
| 公开下载、旧版升级及重启验收 | 公开下载完成：8 个附件、15 个分片与 1 个原始引用的签名/大小/哈希、离线完整包、API/Atom 版本发现及 .18/.17/.16 修订排序通过。实机升级/重启阻塞：指定设备 SSH 超时，未写设备、未执行正式升级或重启；设备联网后继续按正式 .17 基线验收 |
| 完整 Windows 公开安装包 | 阻塞：依赖正式维护升级与重启门槛。独立公开源码应用构建 0 警告/0 错误；15 项发布冒烟、NTFS/HDR/LSFG/Opti/离线包/重启载荷检查通过；随包维护工具已重新准备并通过 42 文件及正式公钥检查。尚未打包或发布本次完整 Windows 安装器 |
| README | 完成：仅将根中英文 README 与维护 README 已有维护链接 .17 改为 .18；显示版本 1.0.6 不变，未改实质文案 |

只读性测试应同时核对镜像 SHA-256 和系统调用打开方式；修复成功测试应在独立私有 dirty 镜像中完成，不能与只读检查成功混为一谈。

状态用例包含 clean、dirty、休眠、dirty+休眠、无休眠文件但 Windows 缓存日志 v2、未清 v1 日志、MFT/MFTMirr record 3 不一致和无效卷。独立实际修复用例确认只调用一次 ntfsfix，修复前后 `/keep.txt` 内容 SHA-256 保持 `25543f8dbdf88effc95a58365b70f255ac77159691c0f95a3eedf398bb75e520`。静态工具 SHA-256：检查器 `d2039ccf78039122f39835be370c2e91488bd2895b5df06316a84be08ac3bcbf`，ntfsfix `02ba101a6285696b6381923bf729f66a933122d50dd38637b6d2b1fd3878edbe`。

本地复核材料：`windows-installer/work/ntfs-preflight-validation/remote-final-tests.json`、`remote-qa-result.json`，`windows-installer/work/ntfs-tools-functional-55bc6ed493444633b170a21c4298248d/report.json`、对应串口记录，以及 `windows-installer/logs/ntfs-preflight-delivery-20261029.json`。组件复核 ZIP 是局部候选，不能作为完整安装包或公开维护 Release 使用。README 仅同步已有维护链接版本。

2026-10-29 正式交付复核：公开源码提交 `aa3fa0c03faf2e66f6ba25a30c10bfda130c98b2`。维护完整 Windows 回归首次受沙箱 DPAPI 上下文限制，860 项中 797 通过、53 跳过、10 项密钥测试出错；正常用户上下文重跑密钥模块 17 项全通过。独立审查核对 Git 字节、固定源码 JSON、签名分片完全一致。未把这些结果计作实机升级或完整新装。
