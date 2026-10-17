# Maintenance release workflow

用户说“发布”时，按本文件调用现有工具完成准备和发布；不要求用户手工生成密钥、拼接打包命令。本文不代表当前已经获准公开尚未完成的组件。

- README 的任何改动先展示给用户确认。本轮 README 文案已由用户于 2026-10-16 确认；后续如需实质修改，仍须先展示。
- split-lock / OXP3 Light 和 XeSS 两个负责聊天已完成；0.1.4 最终载荷必须核对其最终来源；实际生效的 XeSS 覆盖路径可带实验标记纳入，失败倍率不能宣称可用。
- 更新清单还包括无效串口登录服务重启循环和 AutoFlatpaks `batteryState` 空对象修复。现有实机热修复、新装集成和维护升级交付须分别核验；Bash 维护适配已加入，AutoFlatpaks 仅对已安装且精确匹配的版本提供可选修复，最终签名产物仍须核验，不以清单文字代替实际载荷验证。详情见 `docs/RELEASE-0.1.4.md`。
- 使用 `./steamos-maintenance/release-maintenance.ps1 -Action status` 检查正式密钥。首次使用 `-Action init-key`，以后复用同一密钥；禁止因读取失败或已安装公钥不匹配而重新生成、覆盖或跳过验签。
- `/.release-private/maintenance-ed25519` 仅保存 Windows 当前用户 DPAPI 加密的私钥、公钥和元数据，DACL 限当前用户与 SYSTEM。不要提交、上传、打印私钥或将私钥传给子代理。DPAPI 文件仅凭复制不能跨账户/跨机器恢复；需要独立离线备份时另行设计，不宣称已有可移植备份。
- `-Action init-key` 同时提供规范源码公钥 `steamos-maintenance/trusted-public-key.pem`；已有不同公钥时拒绝覆盖。此操作不修改任何设备的信任。
- 使用 `-Action preflight -Version 0.1.4 -OptiPlugin <最终独立插件ZIP>` 检查依赖；自动找到本地已准备的 OpenSSL，可用 `-OpenSsl` 显式指定。缺失时先解决问题，不用测试用签名适配器生成正式包。
- 使用相同参数并提供 `-OptiRuntime <已发布原始运行库>` 运行 `-Action prepare`，在 `.release-work/` 新建隔离目录，重新准备当前载荷、校验 XMX 原始运行库与已发布描述一致、覆盖显式版本并签名打包。检查 `publisher-report.json` 的 complete 及 `artifacts/release-plan.json`，不把失败目录当正式产物。
- 发布操作仍由代理使用可用 GitHub 工具完成：先审查最终源码/产物与更新列表，再准备草稿。维护仓库为 FlightDan/OneXPlayer3-SteamOS，Tag 为 maintenance-v0.1.4，标题严格为 `OXP3 SteamOS v0.1.4 — Maintenance Tools (Bash Installer)`；Opti 资产使用 release-plan.json 指定的 FlightDan/Opti2XMX / maintenance-assets-v0.1.4。
- 先上传全部引用资产，再开放维护目录；保留旧目录引用的资产。Windows 安装器保持 Latest。相同 Tag 已存在时先核对远端资产，不删除/替换不同内容的公开资产。
- 通过白名单导出源码和独立发布 checkout 发布；不要上传工作区根目录、研究记录、密钥目录或全部内部 Git 历史。
- 公网重新下载脚本、签名目录、核心及引用附件进行验证；Release 说明只填写已完成的验收。
- 实机 QA 公钥不同于正式公钥时，保留验签拒绝，不静默换钥。先审计备份恢复严格 0.1.3 基线；无法证明基线时停止实机升级验收，不自动重装。
- 密钥/发布逻辑属于安全敏感改动：实现后进行独立审查，修正后验证，再使用正式密钥。

当前工具状态和公钥指纹见 [发布工具记录](docs/PUBLISHER.md)。本环境受限沙箱的 DPAPI 用户配置不可用；正式密钥操作需要通过正常权限工具在实际 Windows 用户上下文运行。不要把沙箱解密失败当成丢失密钥或重新生成密钥的理由。

用户确认的顺序：通过检查后发布维护工具 Release，再实机验证正式 0.1.3 → 0.1.4 升级，最后发布 Windows 0.1.4 安装包。维护发布时旧 Windows 安装器保持 Latest；Windows 0.1.4 通过验收发布后再设为 Latest。

2026-10-16 发布后的实机预检发现 EFI/VFAT 与风扇配置元数据接管问题。原 `maintenance-v0.1.4` 资产已公开，不覆盖。修复准备使用 `-Version 0.1.4+maintenance.1` 及对应新 Tag；项目主版本与 Windows 安装包仍为 0.1.4。发布前验证原 Bash 入口的实际 API/Atom 发现结果，不把 SemVer build metadata 当作更高版本或承诺自动更新通知。修订版通过公开下载和实机升级前，Windows 发布门槛保持关闭。
