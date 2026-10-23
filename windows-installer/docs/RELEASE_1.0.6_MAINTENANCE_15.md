# OXP3 SteamOS 1.0.6 — maintenance.15 / Decky 3.3.0

官方商城拒绝 Decky 3.2.10 的列表请求，返回 HTTP 426 和版本升级提示，旧前端随后发生 JSON 解析错误。本次新装与维护载荷更新到官方 Decky 3.3.0，使用官方插件更新 API，不伪装版本。显示版本仍为 1.0.6，维护修订为 1.0.6+maintenance.15，Windows 构建为 20261024-004733。

官方 x86_64 二进制为 34,906,704 字节，SHA-256 `e80d03e641d1766a33a817cb27ab8d2e0a4633685e5d27e4de948a6687526181`；固定源码提交 `67196adfa9b299f20dfb0cc932e88a169417b7d5`，源码 ZIP 为 458,459 字节，SHA-256 `8a111350fb9c826ae7ef91c2c34f089d2f75e2c7938749ff36400faeb48ff96d`。源码、GPL 许可证、VERSION 和生成清单随包提供。准备、维护打包及 Windows 打包均校验完整文件集合、版本、大小和哈希，拒绝旧缓存。

新装 integration、独立 PluginInstaller 和维护事务同步 VERSION；旧签名包没有标记时保留兼容。组件 ID、默认选择、依赖、可用系统条件和中英文选项沿用原有定义，无需新增界面选项。其余整合载荷与 maintenance.14 一致，14 个签名分片中仅 runtime-decky 更新。CPU / RAPL / controls 等既有公开内容逐字节保持；未带入未公开动态功耗研究、私钥、凭据或本地设备记录。公共准备指南清理了一处历史工作站路径。

## 验证结果与边界

针对性生成、规划、事务和 7 种生产打包拒绝夹具通过；[执行代码的 Linux CI](https://github.com/FlightDan/OneXPlayer3-SteamOS/actions/runs/39983473467) 通过。6 项隔离 Linux 新装部署/恢复夹具、独立代码审查、Windows 重建（0 警告/0 错误）、源码与最终成品目录各 15 项发布烟测通过。夹具不等同于实机全新写盘。

既有正式 Ed25519 身份重新签名，publisher complete=true，完整覆盖 32 个目录项、31 个可维护组件和 14 分片；历史引用附件保留。公开 8 个当前附件和 15 个引用附件均匿名重下并校验签名、大小、SHA-256、完整离线内容和 CRC。嵌入脚本 API / 编码 Atom 排序夹具、真实 Atom 发现和 API 403 回退均选择 maintenance.15。

实机使用公开下载后物化的正式包，完成 maintenance.14 → maintenance.15 工具升级、Decky 3.2.10 → 3.3.0、回滚至 3.2.10、重新部署 3.3.0 和最终正常重启。43 个现有插件/设置文件路径的集合与哈希始终保持；最终 Decky、InputPlumber、陀螺仪三项服务正常，根分区只读，无文件或服务待恢复事务。最终 Steam 前端上下文读取自身 v3.3.0 并请求官方商城，返回 HTTP 200、116 个插件。

设备最初已有一次 Decky 自更新，测试前备份该官方 3.3.0 文件，并按经校验的原事务快照恢复 3.2.10，未改写维护索引。首次整代回滚在文件事务开始前遇原生陀螺仪重绑 I/O 错误；正常重启及正式 recover 后，重新回滚、部署和最终重启通过。本次未修改陀螺仪产品代码。现有插件各项功能、游戏、休眠及全新 Windows 写盘不作本轮通过声明。

最终 Windows 完整 ZIP 已通过独立内容审查，官方 Decky、维护器 42 文件清单、版本/构建/源码标识、CRC、无旧 Decky 缓存和私密材料检查均通过。正式 Release 已公开并承担 Latest；完整 ZIP 再从公开入口匿名下载，SHA256SUMS、大小、SHA-256、CRC 及包内元数据均通过。

## 交付核销

| 交付项 | 核销 |
| --- | --- |
| 1. 更新列表与边界 | 完成：商城版本拒绝原因、Decky 更新、新装/维护入口与实测边界见本记录。 |
| 2. 安装与维护同步 | 完成：目录、固定来源、新装/独立部署、维护版本标记、生成清单和生产打包门槛一致；选项/依赖/中英文定义未变，无需修改。 |
| 3. 版本与交付标识 | 完成：显示 1.0.6、维护 maintenance.15、Windows 20261024-004733、Decky 3.3.0；插件和其他运行库版本独立且保持。 |
| 4. 针对性验证 | 完成：源代码回归、Linux CI、6 项 Linux 部署恢复夹具、独立源码/实机证据/成品审查及各 15 项发布烟测。 |
| 5. 维护器签名 Release | 完成：复用正式密钥，从当前执行代码重新准备签名；目录完整，引用附件先齐备，维护 Release 不承担 Latest。 |
| 6. 公开下载与实机升级 | 完成：8 个当前附件和 15 个引用匿名复核；正式工具升级、Decky 升级/回滚/重新部署/重启和官方商城请求通过，原插件设置保持。 |
| 7. Windows 完整包及 Release | 完成：同一最终源码全新生成 Decky 与 42 文件维护载荷，校验清单未变；PublicRelease ZIP、成品烟测、独立审查、正式 Latest 和公开下载复核通过。 |
| 8. README 版本号 | 完成：根中英文及维护 README 仅替换已有维护下载链接修订号至 15；安装器 README 无对应链接，无需修改；显示版本未变。 |
| 9. 最终核销 | 完成：安装入口、最终载荷、正式维护发布、公开下载、限定实机验收、完整 Windows Latest 与文档版本链接全链路核对。 |

正式 Windows 源码：`20fbe5c6d4814f583d94e306b1b5cdb07173a3bf`；维护执行代码：`5af0f8f2df56b3b88f69348cfef9e8ee6b3834f6`。两者执行代码相同，前者只额外同步 README 链接和清理历史文档路径。后续本验收记录为文档提交，不替换已公开附件或修改其源码标识。

[维护 Release](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/maintenance-v1.0.6%2Bmaintenance.15) · [Windows Release / Latest](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/tag/v1.0.6%2Binstaller.20261024.004733)

Windows ZIP：564352009 字节，SHA-256 `e5a3cfc724af18cff91e7035d01d28b74e29714cbc0d01e7e5b5794dae2487e9`。

完整离线维护 ZIP：269988310 字节，SHA-256 `937ff906caa6bc24ba40313f0a93139addffdc6e41762988595401d57219ecba`。
