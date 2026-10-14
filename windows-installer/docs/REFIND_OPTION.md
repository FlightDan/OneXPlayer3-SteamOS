# rEFInd 安装与恢复

2026-10-14：第 5 步“启动器安装”已接入实际安装，默认不勾选。勾选后选择默认系统和等待时间，点击“开始安装”时随 SteamOS 写入。配置预览/导出仍可单独使用；它本身不执行安装。

## 安装范围

- 离线载荷固定为 rEFInd 0.14.2（Arch 0.14.2-3，x86-64）；来源与许可位于 components/refind/SOURCE.md、LICENSE.txt。
- 在独立工作映像中先完成组件配置，再向新 SteamOS ESP 安装 rEFInd。用户选择的预部署源映像不被原地修改。实际磁盘写入沿用已有确认范围、逐字节读回和 EFI 注册流程。
- EFI/BOOT/BOOTX64.EFI 原件保存在事务记录与 EFI/OXP3-rEFInd/steamcl-original.efi。SteamOS 菜单调用原位置 EFI/steamos/steamcl.efi，保留官方 A/B 选择，不固定直启某个槽位或内核。
- 菜单按 GPT 分区 GUID 指定 SteamOS ESP 与 Windows 系统 ESP；没有唯一 Windows 系统 ESP 时，不生成 Windows 项，并拒绝选择 Windows 为默认项。
- 本组件不写 Windows ESP。启动器页的“将启动管理器设为默认启动项（推荐）”独立控制固件顺序：内置实盘默认勾选，安装后把 SteamOS (OXP3) 排到 BootOrder 首位，重启先进入 rEFInd；取消则保留原默认顺序，需手动从固件菜单选择 SteamOS。外置盘与演练不修改主机启动顺序。菜单默认系统只控制 rEFInd 内的选择；原 BootOrder 写前备份，Windows Boot Manager 保留。
- 安装前先保存 BitLocker / 设备加密恢复密钥、暂停保护，再关闭 BIOS / UEFI 安全启动。关闭安全启动或修改启动顺序可能导致加密盘无法自动解锁。验证 Windows 正常启动后恢复保护，详见 [安装指南](INSTALLATION_GUIDE.md#1-安装前准备)。
- 菜单默认使用 Graphite Quiet 暗色主题：炭黑背景、低亮度 SteamOS / Windows 剪影、明确的选中边框。256 像素系统图标、96 像素工具图标。OXP3 已反馈启动阶段没有触屏，配置改为加载 UsbXbox360Dxe v1.8.0 手柄驱动：十字键或左摇杆选择，A / Start 确认，B 返回，也可使用键盘方向键和 Enter。用户已确认启动阶段十字键与 A/B 可用；左摇杆、Start 及启动后手柄状态未单独确认。等待 0 表示一直等待；界面倒计时范围为 1–3600 秒。旧安装和旧 ZIP 不会自动更新。

components/options.json 中历史 repairs/refind 保持不可用，因为 rEFInd 已在独立启动器阶段执行，不能再次交给根系统修复管线。catalog.json 登记实际启动器阶段的可用状态。

## 修改与卸载

以下命令在已安装 SteamOS 的终端执行；/esp 必须是这次安装的 SteamOS ESP 挂载点。先核对挂载位置。

```sh
sudo python3 /esp/EFI/OXP3-rEFInd/manage.py verify --esp /esp
sudo python3 /esp/EFI/OXP3-rEFInd/manage.py configure --esp /esp --default SteamOS --timeout 5
sudo python3 /esp/EFI/OXP3-rEFInd/manage.py uninstall --esp /esp
```

配置中断后可执行 resume --esp /esp，或直接执行 uninstall --esp /esp 恢复原件。卸载中断时脚本本身可能已移除，此时从完整安装包的 components/refind/manage.py 运行相同命令。系统无法启动时也可从 Linux 恢复环境挂载对应 ESP 后运行包内脚本，将 --esp 改成实际挂载点。

卸载优先恢复原 fallback，再移除本组件文件。事务记录 EFI/OXP3-rEFInd/state.json 保留供审计和幂等重试；其他文件及目录不递归删除。重复安装不会用 rEFInd 本身覆盖第一份原件。发现用户改动过托管文件时停止覆盖，需先保留改动并人工复核。

手柄驱动和 `EFI/Xbox360/config.ini` 纳入同一事务，安装中断可继续、卸载会移除这次安装的配置与驱动。已有同名外部配置时拒绝覆盖。驱动生成的诊断日志保留。升级旧安装需用新完整组件载荷执行 `install`，旧 ESP 内的 `manage.py configure` 只调整原版本的默认项与等待时间。驱动会跨固件可见的文件系统查找配置，其他 ESP 中已有 `EFI/Xbox360/config.ini` 时需要检查是否加载了那份配置。

系统更新可能重新生成 fallback；若发生这种情况，文件冲突检查会阻止直接覆盖。此版本不安装后台服务来强行恢复 rEFInd。

## 验证边界

此前的菜单/倒计时与配置导出测试未覆盖实际安装。此次新增 scripts/test-refind-installation.ps1，只接收带所有权记录的独立工作映像，在 QEMU/OVMF 中执行实际 FAT 文件事务、重复安装、逐文件中断/继续、用户修改保护、卸载恢复、SteamOS 链式启动和 Windows EFI 测试入口。具体记录见 work/refind-acceptance-20261014/acceptance.json 与该目录各阶段日志；打包时另附整理后的 docs/REFIND_ACCEPTANCE.md。

Windows EFI 测试入口只是可辨识的 EFI 程序，不是真实 Windows 系统。实机启动菜单中的十字键与 A/B 已由用户确认可用；Windows 系统启动、掌机触屏、内屏方向和 Secure Boot 整条链尚需实机验证。注入的进程中断也不等同于物理掉电。

手柄改动的目录级事务测试见 `components/refind/test_gamepad.py`，覆盖所有文件边界的中断恢复、旧事务记录升级、外部配置保护、配置修改保护和驱动类型检查。此前 QEMU 验收不覆盖新驱动，键盘事件注入也不能证明物理手柄有效；用户已确认实机启动菜单中的十字键与 A/B 可用。左摇杆、Start、松手后停止移动，以及启动 Windows / SteamOS 后手柄是否正常，尚未单独确认。

2026-10-14 手柄组件验证：6 项目录级事务测试通过（24 个文件位置的安装／卸载中断恢复）；独立 `Gamepad` 构建 0 警告／0 错误，启动器页面 `--boot-setup-checks` 通过。`scripts/test-refind-gamepad-qemu.py` 的倒计时与键盘 Enter 两项通过，记录位于 `work/refind-gamepad-qemu-f8da61731d9f4a7d855fba62aacd92be/report.json`，只证明带驱动配置的 rEFInd 能进入 EFI 测试入口。额外全量 `--options-checks` 在 `refind-install-available-and-opt-in` 条件失败，未通过后续全量界面检查；不将其记为通过。没有真实设备 EFI 写入或手柄按键验收。

已安装系统的独立更新组件：`dist/refind-gamepad-update-20261014.zip`，包含完整 rEFInd 组件载荷及 `GAMEPAD-UPDATE.txt`。按说明从新包运行 `configure --payload .` 可更新有本工具事务记录的旧安装，无需重装系统。

上游说明：[rEFInd](https://www.rodsbooks.com/refind/)、[SteamOS A/B chainloader](https://github.com/evlaV/steamos-efi)。

## 2026-10-14 手柄驱动扫描修复（已由用户确认可用）

当时用户反馈最新本地包 `20261014-210439` 的启动菜单中十字键与 A/B 不可用。实机检查确认驱动、按键配置和管理事务齐全；配置却使用了不被随包 rEFInd 0.14.2 识别的 `driver_dirs`。驱动位于独立目录，也不在 `EFI/BOOT/drivers_x64` 默认扫描位置，因此该配置不能让 rEFInd 加载它。后续已改正配置并由用户确认启动阶段十字键与 A/B 可用。

生产配置、向导导出、示例和 QEMU 测试已统一使用 `scan_driver_dirs /EFI/OXP3-rEFInd/drivers_x64`。Python 的 7 项配置与事务测试通过，新增回归直接读取随包 EFI 二进制的关键字表，避免再次只检查文件存在或重复错误模板。

安装器编译无警告、无错误；81 项 WPF 启动器检查和 2 项 QEMU 倒计时/键盘确认测试通过。独立复核未发现遗漏的部署或打包路径。证据见 `logs/refind-scanfix-20261014.json`；这些自动检查未覆盖实体手柄输入，实机按键可用状态见下方用户确认。

实机已备份旧事务、管理脚本及菜单配置，再用安装器事务更新管理脚本和两份 `refind.conf`。默认 SteamOS、2 秒等待、原始启动文件备份和固件启动项均保留。用户随后确认启动菜单中的十字键与 A/B 已可用。当前固件优先项是直接启动 SteamOS 的入口；测试 rEFInd 时应选择 `SteamOS (OXP3)`。
