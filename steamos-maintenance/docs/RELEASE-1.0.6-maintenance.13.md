# OXP3 SteamOS 1.0.6 — maintenance.13

中文组件列表曾把 `Supported exact SteamOS baseline` 和旧版 OXP3 基线通过说明显示成“暂不可安装”。本修订改为“系统版本检查通过；点击‘检查更改’继续安装预检”。未知说明保留原始详情并使用中性前缀；真实受阻项目仍由结构化预检结果禁用。

项目显示版本维持 1.0.6，维护修订为 1.0.6+maintenance.13，Windows 新构建为 20261023-103000。执行源码固定为 `a2e268b802da7c5aaf64f0be57688b2115d9a2b8`；发布后的文档核销不改变该构建身份或附件。继承 maintenance.12 的正式公钥、迁移桥和恢复记录。

| 必查项 | 核销结果 |
| --- | --- |
| 1. 更新列表 | 完成：修正中文正常说明、未知说明；影响维护器与 Windows 随包维护工具。组件功能及支持系统未扩展。 |
| 2. 安装脚本、组件清单与载荷 | 完成：从隔离正式源码重新准备并校验 42 个随包维护文件和生成 manifest。组件 ID、默认项、依赖、安装脚本与选项未变，相关目录无需修改；rEFInd 仍为独立安装／恢复操作。Windows 新装载荷生成测试 3/3 通过；未执行完整新装写盘。 |
| 3. 版本与交付身份 | 完成：1.0.6 / maintenance.13 / Windows 20261023-103000；新 Tag、新附件及源码身份固定；未覆盖旧资产。Opti2XMX 0.2.8、XMX 原始运行库及组件独立版本不变。 |
| 4. 针对性验证 | 完成：71 项维护回归和 3 项随包生成测试通过，独立源码审查通过；Windows 重建 0 警告／0 错误，源码与成品目录各 15 项非破坏性发布烟测通过。完整 ZIP 独立审查核对 1,376 文件、42 个维护文件、9 个嵌套归档及隐私边界；17 个常规 CPU 项与已公开 m9 字节一致。 |
| 5. 维护器 Release | 完成：status、preflight、prepare 使用原正式 Ed25519 身份，publisher complete=true；最终核心源码与固定提交一致，32 目录项／31 可维护组件／14 分片完整；全部 14 分片复用历史固定摘要与地址。六个本次附件核对后公开，历史引用全部保留；维护器不承担 Latest。 |
| 6. 公开下载与实机升级 | 完成：六个当前附件、15 个历史引用均匿名重新下载核对；目录与核心签名、SHA256SUMS、Bash 内嵌信任、API 和真实 Atom 回退发现及修订排序通过。实机由公开 .12 工具限定升级到公开 .13，正确显示系统版本检查通过，无 pending；组件修订、公钥、Opti 文件、根只读保护与启动 ID 不变。工具计划 restart_required=false，系统重启与恢复演练不适用。 |
| 7. Windows 打包与 Release | 完成：同批正式源码刷新随包运行时及 manifest，check-maintenance 与相关载荷检查通过；使用 make-development-package.ps1 -PublicRelease -Format zip -SourceCommit 生成完整包。维护门槛通过后公开并设为 Latest；最终完整 ZIP 再次匿名下载，大小、SHA-256、CRC、版本及 build-info 源码身份通过。 |
| 8. README | 完成：仅将根目录中英文及维护 README 的现有维护脚本链接版本同步至 maintenance.13；其他介绍与安装文案不变。显示版本未变，其他 README 不需修改。 |
| 9. 最终核销 | 完成：安装入口、最终载荷、签名维护发布、公开下载与限定升级验收、Windows Latest、README 链路均核对。工作区已有未发布改动保持原状，发布使用独立公共源码 checkout。 |

实机还对截图中的 Opti2XMX、游戏模式环境隔离及 Decky 依赖执行最终签名载荷的真实安装预检，均为 ready，can_apply=true；这些组件当前安装状态均为 true。本轮仅应用维护工具升级，没有重复应用组件。若重新应用环境隔离组件，其组件计划要求系统重启；这与本轮无需重启的工具升级不同。

未执行全新 Windows 物理写盘、重复安装组件、硬件功能或游戏性能验收，未将源码或预检结果替代这些实测。未公开动态功耗研究、核心算法、设备记录、凭据与私钥未进入新源码提交、维护器或安装包。

完整 Windows ZIP：555,700,580 字节，SHA-256 `b613d7ce002a7929d6940652253e8a2a2afa5fbd13701be914d9a1a7580e2679`。

维护核心：1,057,799 字节，SHA-256 `3cf631abe45db99f66b752cfe68607049f35f99350026e480c97694f4a9b8a0c`。

[Windows Latest](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/v1.0.6%2Binstaller.20261023.103000) · [Maintenance](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v1.0.6%2Bmaintenance.13)
