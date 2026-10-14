# 重启进入 Windows

安装助手“第三方插件预装”中的 **重启进入 Windows · Decky 按钮与桌面快捷方式**（`windows-reboot`）默认开启，依赖 Decky Loader。源码与已编译前端随 `components/windows-reboot` 携带，不需要联网下载插件，也不要求安装 rEFInd。

游戏模式在 Decky 中打开 **Restart into Windows / 重启进入 Windows**；桌面模式双击同名快捷方式，应用菜单也有入口。两者都会先检测 Windows 启动项，确认后才重启。请先保存游戏和文件。

## 行为

- 从 `efibootmgr -v` 中识别指向 `\EFI\Microsoft\Boot\bootmgfw.efi` 的启动项，要求唯一且已启用，不使用固定编号。
- 未找到、已禁用或存在多个 Windows 启动项时显示原因，不自动创建、删除或启用启动项。
- 确认后重新检测目标，设置 UEFI BootNext，读回一致才执行正常的 `systemctl reboot`。只设置下一次启动，不修改 BootOrder。
- 重启请求失败时，若 BootNext 仍是本组件写入的值，则恢复之前的值；原来没有则清除。若其他程序已改写，保留其值。恢复失败会明确报告。
- 安装、首次启动、加载插件和刷新状态均不会设置 BootNext 或请求重启。

## 部署与恢复

通过现有文件事务分别部署两个系统槽，共享 home 快捷方式只保存一份原件。插件位于 root 拥有、deck 可读的目录：

```text
/var/lib/oxp3-installer/decky/runtime/plugins/oxp3-restart-windows/
/usr/local/lib/oxp3-windows-reboot/{boot.py,desktop.py}
/usr/local/bin/oxp3-reboot-windows
/usr/share/polkit-1/actions/org.oxp3.restart-windows.policy
/etc/polkit-1/rules.d/49-oxp3-restart-windows.rules
/home/deck/Desktop/oxp3-reboot-windows.desktop
/home/deck/.local/share/applications/oxp3-reboot-windows.desktop
```

Decky 后台带 `root` 标记，只暴露状态和确认重启两个 RPC。桌面界面由普通用户运行，通过 pkexec 调用固定程序；仅本地活动会话的 deck 用户可免密码调用。程序只接受 `status` 或 `reboot <四位大写启动编号>`，并再次核对编号是否为唯一 Windows 启动项。Python 使用 `-I -B`，不提供任意命令执行接口。

目标镜像须自带 `/usr/bin/python3`、`efibootmgr`、`systemctl`、`pkexec`、`kdialog`；缺少任一项时跳过整项并报告原因。特权文件或目录存在不可信权限时拒绝部署。安装阶段不读取或修改宿主 Windows 的固件设置。

恢复使用现有 `integration_runtime.py restore --component windows-reboot` 流程。有快捷方式或后台文件编辑冲突时保留整套组件。移除 Decky 前须先恢复本组件。恢复当前槽不会修改另一槽的系统文件；完全卸载需分别处理两个槽。

## 构建与验证

在 `components/windows-reboot` 使用锁定的 `pnpm-lock.yaml` 安装开发依赖后，从安装助手目录运行：

```powershell
./scripts/build-windows-reboot.ps1 -NodeExecutable node
python -B components/test_windows_reboot.py
node components/windows-reboot/test_frontend.mjs
node scripts/run-guest.mjs component-tests
```

构建脚本也接受 `-DependencyRoot` 指向匹配的现有 `node_modules`。它在忽略的 work 目录执行 TypeScript 检查、Rollup 构建和交互检查，将 `dist/index.js` 放回组件。安装助手运行时不需要 Node.js。打包携带整个 components，运行 `validate-windows-reboot-payload.ps1` 检查必需载荷、版本、Decky 权限标记与 KDE 确认框参数；不满足条件时拒绝打包。

测试使用假固件验证检测、写后验证、重启失败回退和取消逻辑，并在断网 Linux 虚拟机里验证文件事务、独立 A/B 根目录加共享 home、重复安装、权限和恢复。这些测试不等于真实 Windows 启动验收。

2026-10-14 验证：TypeScript、Rollup 和编译后前端交互检查通过；断网 QEMU 组件回归 79 项通过（含本组件当时的 18 项），证据保存在本地 `logs/2026-10-14T10-30-28-218Z-component-tests.{json,txt}`。随后新增的系统工具错误输出和缺少 UEFI 两项检查在 Windows 侧通过，当前测试文件共 20 项，其中 4 项文件生命周期测试需要 Linux root。WPF `--options-checks` 在本次执行环境启动失败（0xc0000142），没有将历史界面检查结果算作本次通过。

2026-10-14 已通过 SSH 部署 0.1.1 到当前 ONEXPLAYER 3：实际 Decky 后台 UID=0、加载日志与 Windows `0000` 状态检查通过；polkit 本地活动会话授权通过。桌面入口改用当前 KDE 支持的 `--warningcontinuecancel`，已验证对话框能够打开；菜单图标限制为 `1em`。补上了当前 efibootmgr 的非 File() 包裹路径格式识别。当前测试共 22 项，其中 4 项需 Linux root。

本次 SSH 部署只检查状态和离屏对话框，没有代替用户触发系统重启，系统只读保护已恢复。随后用户明确确认“已经重启了，成功了”，实机重启进入 Windows 验收通过。该 0.1.1 载荷已同步安装助手，并与部署到掌机的归档逐文件比较一致。全新安装与之后的默认启动行为仍需分别验收；历史 ZIP 不会自动更新。
