# 显式首次启动分发入口

本页描述 `components/firstboot.py` 的专用资源预览/验证入口，该入口仅实现 HDR 适配器，携带资源不代表安装选择。正常七步安装已使用独立的 `components/integration.py` 与 `integration_runtime.py` 管线，状态路径为 `/home/.oxp3-installer/integration`，见 [组件说明](COMPONENT_INTEGRATION.md)。下文的 firstboot 请求、HDR 拒绝测试和历史记录仅适用于专用入口，不能用来判断正常安装是否接入。

代码固定于各槽 `/usr/local/lib/oxp3-firstboot`，root拥有，组/其他用户不可写；启动前检查整个代码树和祖先。systemd oneshot以 `/usr/bin/python3 -I -B` 运行，在local-fs之后、display-manager之前，通过RequiresMountsFor等待共用home。请求/结果/staging位于 `/home/.oxp3-installer/firstboot`，目录0700、文件0600、root拥有。home必须独立挂载、root拥有且组/其他用户不可写。

请求包含固定schema、UUID、显式组件、源版本/build和deck用户。第二槽准备沿用同一请求及状态inode，不创建第二份选择记录。未知/重复组件写前拒绝；不同请求保留已有操作；源版本/build变化要求显式重新审阅。已完成或恢复的操作不自动重装。跨槽操作共用flock。

HDR先进行只读兼容性检查，拒绝记为preflight_refused/files_changed=false。只有文件安装成功才记files_installed/session_restart_required并注册恢复入口，不自动重启Gamescope。被拒绝组件恢复返回not_installed，不创建HDR配置或事务。

离线staging先核对全部源和已有目标，重试只补齐相同不可变文件；先验证共用home私有状态再创建代码，服务启用链接最后写入。它不执行systemctl或启动服务。空选择强制不启用。所选槽var内存在旧firstboot记录时，staging和运行/恢复均拒绝；旧HDR日志也拒绝覆盖。旧历史迁移/两槽合并和代码升级尚无接口。

本轮实际虚拟验证：两槽准备使用同一request UUID和记录；空选择/重复不改状态、未知/重复拒绝、请求变更保留原状态、用户可写代码拒绝均通过。随后一次真实UEFI启动，systemd执行次数2→3、新boot ID；独立只读新VM确认A/B两根视图共用同一inode/request/result、实际3.8拒绝HDR且未创建配置/事务、根保护及原Windows保留文件完整。证据：`../logs/shared-firstboot-systemd-20261013.json`。两个挂载视图不能算两次槽位启动；夹具没有Windows操作系统。

此前每槽存储的B槽执行1→2验收保留于 `../logs/firstboot-dispatch-20261013.json`，用于历史范围；当前共享路径以上述新结果为准。最初home误判Btrfs及仅准备A导致失败的日志保留，后来已修正为ext4 ro,noload与两槽准备，不计失败为通过。

CLI：`--cli virtual-firstboot <media.img> <completed-fixture.qcow2>` 新建隔离overlay，准备→实际UEFI→独立只读证明；`virtual-firstboot-verify` 复查已启动后的自有证明盘。只读后备图按每层有界QCOW2本地名称解析规范路径，全部read-only；循环/特殊路径/重定向拒绝。独立VM须实际打开完整图。开发包work外部基线别名不进入ZIP，也不是任意目录可移动性证明。

该专用入口没有取代正常集成管线。实际双槽启动/系统升级、OXP3 HDR 显示恢复、Decky/插件的用户会话、断电及硬件验收仍需设备测试。文件恢复仍需新游戏模式会话才反映到显示链路。

systemd单元语义的官方参考：[systemd.unit](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml)。QEMU块图参数参考：[QEMU invocation](https://www.qemu.org/docs/master/system/invocation.html)。实际结果以上述本地证据为准。

20261013-132846自带运行时复验通过：r3介质只读、跨槽文件恢复、19项事务/生成器检查、实际子进程退出及异挂载恢复、LuaJIT harness、A/B共用请求准备和真实UEFI/systemd执行2→3，再由独立只读VM确认共用结果与无HDR配置/事务。未证明双槽均启动、系统更新或正向实机HDR。索引：../logs/portable-20261013-132846-final-verify.json。
