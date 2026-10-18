# KDE 分区自动挂载：未发布候选交付记录

2026-10-19 后续修订及当前交付核销见 [maintenance.3 候选](RELEASE_1.0.6_MAINTENANCE_3.md)。下文保留 10 月 18 日原候选证据，不作为本次最终验证结果。

日期：2026-10-18。现有整合版本源仍为 `components/release.json` 的 1.0.6。本文不代表已经发布新的 1.0.6 安装包或维护修订。正式发行版本与签名产物须在验收后独立确定，不覆盖已公开附件。

## 本次变更

- 新增 KDE 原生对话框工具：启用、查看、取消分区自动挂载，桌面与应用菜单均有入口。
- UUID 持久配置；当前槽 fstab 独立管理块；备份、原子更新、冲突拒绝。
- 支持 NTFS/ntfs3、exFAT、ext4 数据分区；过滤系统/恢复/只读分区，重复 UUID 拒绝。
- 已有 KDE 本次挂载、立即挂载失败、取消授权分别报告；不强制挂载 NTFS 脏卷、不格式化、不删除分区、不自动创建 Steam 库。
- Windows 新装与维护器统一组件 ID `partition-mount`、默认安装工具；安装阶段不实际配置分区。
- 本机 QEMU 使用独立测试任务；无网络、无掌机连接、无 SSH。

## 发布核销

| 项目 | 状态与证据 |
| --- | --- |
| 更新列表及边界 | 完成：本文与 PARTITION_MOUNT.md；明确当前槽、文件系统和授权限制。 |
| 安装/维护选项、部署、恢复、双语 | 完成：统一 ID/default/依赖，五个固定部署目标与冲突拒绝、可执行依赖检查；恢复不接管用户后期 fstab。维护专用 options 不重复列主选项。 |
| 载荷与源清单重新生成 | 完成本地候选：prepare_payload.py 重新生成受影响源码载荷，resource_complete=true、partition-mount=adapter_supported；本组件源一致性核验以 maintenance-payload-live-final 为准，5份部署源码逐字节、大小、SHA-256及来源清单一致。该工作区整套输出不是正式发行输入；正式包必须在隔离公开基线保留已发布CPU并排除私有研究后重新准备。新装组件直接读取 components 的固定文件，不使用 generic integration manifest，prepare-integration.py 无本次专用载荷。随安装器的 cache/maintenance 已刷新且 check-maintenance.ps1 -RequireKey 通过；旧缓存保留在候选目录 previous-maintenance-runtime。 |
| 版本与交付标识 | 未发布候选；保留已公开1.0.6；正式修订号尚未分配。 |
| 源码/隔离Linux验证 | 完成：33项断网QEMU测试通过（23后台/GUI响应，8新装文件映射，2维护规划）；24项维护准备/兼容性回归通过，另1项分片完整性测试通过；Windows构建0警告0错误。独立审查发现的UUID克隆、设备别名、automount重复启用、systemd覆盖和不可执行依赖已修正并回归。 |
| 实机新装/维护升级/重启/GUI | 完成独立试部署：用户后续授权 SSH、KDE 与一次重启；OXP3 3.10 B 槽验证 KDE 原生 Wayland 与 XWayland 窗口、私有 loop ext4/exFAT 实际挂载及重启按需挂载、原配置恢复。未完成：NTFS、GUI管理员授权完整保存流程、完整新装及签名维护升级；不能用独立试部署代替。 |
| 维护器签名发布 | 阻塞：status及现有1.0.6+maintenance.1元数据的只读preflight均报告无法检查现有正式密钥权限；试探下一内部修订的preflight还因尚未创建修订元数据而拒绝。未执行prepare签名，不重新生成密钥、不跳过验签，未发布。正式修订须另行分配，不能重用已公开元数据。 |
| 公开下载和升级验收 | 阻塞：本次没有公开产物；不能以本地测试代替。 |
| Windows完整安装包与发布 | 阻塞：维护发布和实机升级验收门槛尚未通过，不能发布对应完整安装包。 |
| README | 不适用：当前没有正式版本变化，未修改 README。 |

研究限制继续生效：本工具自身不引用动态功耗研究代码。完整发行前仍须核对全部公开源码和实际打包载荷；本轮新增工具验证不构成对全套现有载荷的公开许可或审计结论。

## 验证边界与证据

- 最终 QEMU：`windows-installer/logs/2026-10-18T13-19-32-511Z-partition-mount-tests.{json,txt}`，31+2项全通过；网络禁用、source/target均为null，只挂私有scratch与只读测试文件盘。
- 生命周期测试实际写入并回读隔离临时 fstab/备份/目录，模拟 lsblk、systemd、findmnt 响应；覆盖设备消失、重复启用、KDE现有挂载、autofs、错误设备号、授权取消、配置冲突、符号链接、不可执行工具和写失败。**未使用真实磁盘挂载、实际systemd管理器、KDE图形桌面或重启验收。** QEMU开关机本身不代表SteamOS挂载配置重启验证。
- 分片测试只用现有测试签名适配器和fixture，检查组件目录、核心排除及5份文件完整性；不是正式密钥产物。
- 生成资源：`windows-installer/work/partition-mount-candidate-20261018/maintenance-payload-live-final/components/preparation-report.json`；此前final/live-candidate仅为较早快照，不作为后续打包输入。
- 本次5份源码哈希核验：`windows-installer/work/partition-mount-candidate-20261018/partition-mount-payload-verification.json`。未发现研究目录或密钥目录路径被当作资源来源；现有其他组件仍需发行前独立审核。
- Windows：`scripts/build-app.ps1`成功；维护运行时35文件，`prepare-maintenance.py --check --require-key`及`check-maintenance.ps1 -RequireKey`通过。

## 后续掌机试部署与重启验证

用户随后明确撤销此前禁止SSH的限制，并确认可以切KDE、重启测试。通过原固定主机密钥连接，先只读确认 SteamOS 3.10 / build 20260924.1000 / OXP3、当前及下次启动均为 B 槽，无系统更新任务、无运行中的游戏。部署前后原 fstab 保持一致。

使用 root 私有192MiB文件镜像的两个GPT分区做ext4/exFAT测试，格式化前核对 loop backing file、sysfs父盘、分区编号和设备号。没有选择NVMe/SD现有用户分区。实际工具的保存、立即挂载、同分区重复启用均成功；KDE主菜单与已保存列表截图检查通过，另验证原生Qt Wayland插件和窗口。

一次真实重启后，boot ID发生变化，两份`.automount`均为active/waiting，`.mount`初始inactive；读取测试文件触发实际ext4/exFAT挂载，UUID、设备号和内容匹配。测试之后取消两条配置、卸载并detach测试loop、移除临时启动服务和wants链接；fstab恢复部署前逐字节相同，系统只读保护仍为enabled。镜像与恢复记录保留在root私有目录；GUI工具和桌面/菜单入口保留，最终在KDE打开主窗口供用户使用。

实机列表发现OEM `RecoveryImages` 使用普通数据分区类型，新增前缀卷标过滤并同步回归测试。最终掌机`mounts.py` SHA-256为`3623ad92469b29e682badf5d480c8acd3684f02e76a44ea2d7bd622be15b83b2`，与最终源码/载荷一致。该项修正后的Windows便携测试11项通过、20项Linux专用跳过；独立审查和33项隔离Linux结果见上文。

原始私有记录在本地`tools/partition-mount-live-20261018/`，包含前后重启结果、真实挂载、清理核验及限定窗口截图；不纳入公开源码/安装包。试部署原文件事务保留在掌机`/home/.oxp3-partition-mount-qa-20261018`，恢复入口为该目录的`restore-tool.py`；先在GUI取消日后新增的挂载，再通过sudo执行。签名维护器尚未接管本次独立试部署，正式接管前须按原事务恢复或显式验证接管，不把试部署当成已完成升级。
