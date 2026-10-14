# HDR Gamma22 独立配置组件

当前资源 revision：20261013-hdr-r3。本页说明独立 HDR 资源与恢复接口；高级预览的“携带资源”入口默认不选。正常七步安装向导中的 `hdr` 修复默认开启，由 `components/integration.py` 配置到目标镜像，两个入口不能混为一谈。安装器不自动重启当前会话；新装显示效果仍需设备验收。

配置来自维护仓库最新 HDR 模板：SDC / 精确 AMS881KB01-0，Gamma 2.2，1100/472 映射，首次匹配强制合成及 OnPostPaint 纠正。1100 是软件映射参数，不是光学测量。保留色度、30–144 Hz 表与60/144 Hz锚点。生成器直接验证并输出已固化模板；旧475模板或缺少合成逻辑时拒绝。上游 Lua 的 MIT 许可随资源提供。

Live apply 只接受 SteamOS 3.10 build20260924.1000、内核7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9、Gamescope3.16.30-1、ONE-NETBOOK / ONEXPLAYER 3、xe和非root deck账号。Gamescope包版本来自本地20261012-baseline/hdr-readonly原始记录。面板精确匹配在 Lua 中继续生效。任一不匹配先拒绝，再创建状态。当前3.8.14介质的实际chroot拒绝已验证；不是对3.8.14的运行适配。

独立入口 `components/hdr/installer.py apply` 在真实目标根执行，支持 Python `-I -B`，也用于 root 拥有的专用首次启动验证。正常安装使用单独的 `components/integration.py` / `integration_runtime.py` 管线，见 [组件说明](COMPONENT_INTEGRATION.md)。独立入口只修改 `home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua`。已有文件保留原内容快照、uid/gid/mode；新文件属于实际 deck 账号。重复安装保留首次原件；手工改动或权限变化发生冲突时拒绝覆盖。

恢复入口 `installer.py restore --root <已挂载系统根>`，可在恢复环境使用不同挂载点。日志只用该配置的逻辑相对路径，状态保存在独立挂载的共用home中：`home/.oxp3-installer/transactions/hdr`，root拥有、0700/0600。恢复后原本不存在的文件会移除；原件字节和元数据恢复。每次恢复后重装创建新epoch，旧日志保留。其他组件和用户Lua不属于此事务。

安装/恢复均不会修改KDE HDR/WCG、亮度、内核、启动参数或服务。它们不会重启或控制Gamescope；运行中已加载的Lua仍须新的游戏模式会话才变化，状态明确标记session_restart_required。文件恢复不等同于当前显示链路已切回SDR。

虚拟验收：15项通用文件/目录事务及4项生成器检查通过；真实SteamOS3.8.14的隔离Python拒绝、现存用户配置重复/保留原件、手工编辑冲突、新文件所有权、新epoch、独立子进程写入/fsync后提交前退出，以及不同挂载点恢复原始不存在状态通过。实际目标系统的LuaJIT执行Gamescope API行为harness，通过精确面板、首帧/SDR/HDR合成纠正、稳定帧日志和模式锚点；harness没有真实显示驱动或Steam会话。

开发CLI：`--cli virtual-hdr <media.img> <completed-fixture.qcow2>`，始终新建隔离overlay。`--cli refresh-hdr-resources <owned-preview.img>`仅更新本工具预览的资源；发布/硬件阶段不使用该开发入口。Windows界面新增“携带HDR配置与独立恢复工具”，默认不选。

正常安装器请求交接、实际3.10新装/重复安装/显示恢复、重启/休眠及长期性能、更新/A-B仍待验收。当前没有改变掌机配置；资源携带和虚拟文件事务不作为这些通过证据。
此前r2的 `20261013-115518` 包内运行时在受限 PATH 中重新通过上述生命周期及实际进程退出恢复；最终r2资源断网只读复验、未激活状态和UEFI可见安装首页通过。证据：`../logs/portable-20261013-115518-verify.json`。


2026-10-13：r3加入shared_state.py，状态基目录0700/root，要求home是独立、root拥有且组/其他用户不可写的真实挂载。A/B两根共用一个状态inode，保留原件、epoch、锁和恢复结果。所选根var下若有旧HDR日志，先拒绝并保留；尚未实现旧日志迁移/两槽旧历史合并，也未证明实际系统更新后的显示运行。journal内部r1标识仍是原逻辑文件格式契约，与r3资源版本不同。

20261013-132846自带运行时复验通过：r3介质只读、跨槽文件恢复、19项事务/生成器检查、实际子进程退出及异挂载恢复、LuaJIT harness、A/B共用请求准备和真实UEFI/systemd执行2→3，再由独立只读VM确认共用结果与无HDR配置/事务。未证明双槽均启动、系统更新或正向实机HDR。索引：../logs/portable-20261013-132846-final-verify.json。
