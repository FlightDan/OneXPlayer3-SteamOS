# rEFInd 安装、恢复与暗色主题验收

2026-10-14。最终结果索引为同目录 `refind-acceptance.json`，其中保存各阶段结果、检查数量和本地原始记录位置。此前只验证菜单与配置导出的测试，不能替代这里的实际安装测试。

## 环境与实际执行范围

测试通过正常 `SteamOSInstaller.exe` 调用生产安装脚本，在带所有权标记的独立 80 GiB SteamOS 映像上操作 FAT EFI 分区。QEMU/OVMF 启动使用新的覆盖层和独立固件变量文件。测试未写宿主机物理磁盘、Windows ESP 或宿主机固件。

完整脚本为 `scripts/test-refind-installation.ps1`。顺序包括：

1. 实际 FAT 安装与逐字节读回；重复安装保留最初启动器备份；更改默认系统和等待时间；用户修改保护。
2. 21 个托管文件的每一个安装、卸载边界注入进程中断，随后恢复；还原部分安装、恢复配置中断，并核对其他 EFI 文件未变。总计 31 项检查。
3. 安装新主题、设置一直等待，25 秒后模拟 Enter，经官方 SteamOS A/B chainloader 启动至真实串口登录提示。
4. Windows 默认项倒计时，经指定 Windows 测试 ESP 的 GPT GUID 启动可辨识 EFI 程序。
5. 卸载恢复原 fallback 后，重新独立启动 SteamOS 至串口登录提示。

## 视觉与安装器界面

Graphite Quiet 默认暗色菜单使用生成的炭黑背景、低亮度 SteamOS / Windows 剪影、统一工具图标与选中边框。背景、图标、字体与选择框均随托管文件一起安装和恢复。`components/refind/ASSETS.md` 记录背景生成提示词、图标来源和字体许可。

以下为实际已安装菜单的 QEMU 截图，均为 1280×800：

- `refind-dark-menu.png`：SteamOS 选中。
- `refind-dark-windows.png`：Windows 选中。
- `refind-dark-tools.png`：关机工具选中。

独立视觉复查结论为 Ship（限上述截图范围）；原生字体反色导致的暗字问题已修正并复查。rEFInd 0.14.2 GNU-EFI 构建的重复工具项问题通过显式限定工具槽位处理，最终菜单为关机、重启、固件设置和信息四项。

WPF 安装器另通过 1,020 条布局断言（98 个页面/语言/尺寸组合）、39 条选项检查和 70 条向导导航记录。当前正常启动文件是根目录 `SteamOSInstaller.exe`；旧的 `SteamOSInstaller-Touch.exe` 已删除。准备映像与安装内容分离，设备修复/适配默认折叠全选，选项两列，Discover 中文默认开启、英文默认关闭，窗口默认最大化并保留系统栏。

## 尚未覆盖

Windows 入口测试使用 EFI 探针，**不是真实 Windows 系统启动**。SteamOS 证据到达串口登录提示，未覆盖 Steam 前端。实机安装、掌机固件触屏、显示方向、实体输入、Secure Boot 完整链路及物理掉电恢复仍需实机验证。虚拟机中注入进程中断不能等同于突然断电。
