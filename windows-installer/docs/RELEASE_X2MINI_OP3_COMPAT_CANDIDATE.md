# X2mini / OP3 机型兼容分支候选

日期：2026-10-21。分支：`release/x2mini-op3-compat`。
本记录是本地源码候选，不是新 Release；整合版本仍为 `1.0.6`。

后续新增的 X2mini 475/700 HDR 安全试用及最新恢复/载荷检查，见 [独立候选记录](RELEASE_1.0.6_X2MINI_HDR_TRIAL.md)。本页旧测试数字与 `work/model-compat-20261021/verification.json` 只证明当时源码；后续 HDR 文件以 `work/x2mini-hdr-trial-20261021/verification.json` 的哈希和结果为准。维护应用现为 39 文件；原生运行时重编及实机验收仍未完成。

取消维护安装入口、维护组件策略、首次启动激活，以及 CPU、RAPL、遥测、充电、灯光、HDR 和 split-lock 清理入口的产品名/厂商硬拒绝。DMI 仍可用于诊断。保留 SteamOS、内核、软件依赖、CPU 拓扑和实际硬件接口检查。未更改设备、信任密钥、已有公开附件或私有动态功耗算法。

输入配置不再使用产品名。启动前识别唯一 `1a86:fe00` 接口 02，生成带实际 sysfs 路径的运行时配置，避免普通电脑的 Xbox 360 手柄单独触发本项目 profile。原 `/etc` 配置与校准不写回；原版精确 DMI 匹配块可在运行时副本中转换，自定义匹配仍保留。无设备/歧义时使用原装配置。普通 MCU 主机同时插入同名外接 Xbox 的既有选择问题仍待实机确认；设备在服务启动后出现或 USB 重枚举改变路径时，需要重启 InputPlumber 重新生成。

BMI260 包装驱动源码已移入 `components/gyro/`，以 ACPI ID、I2C 地址与读取到的芯片 ID `0x27` 取代产品名/BIOS 字符串，芯片读取在 core 初始化和固件上传之前。内核模块尚未编译：本机没有对应内核的已编译 headers/Module.symvers 和完整构建工具链。安装与维护准备脚本均拒绝旧的机型锁定模块，不能复用旧 `.ko` 冒充本轮载荷。风扇 EC 的板型寄存器布局选择、HID 报文格式选择和实际面板匹配仍保留；本候选不证明 X2mini 与 OP3 的全部底层硬件完全相同。

Double-check 还找到 KDE 桌面 HDR 的固定 KWin 运行时仍含 OP3 DMI 硬拒绝。对应源码现已改为只检查显式 opt-in、内部屏幕和 SDC4301 EDID，并给 KWin 与前端增加 EDID-only 版本标记；精确面板身份仍是硬件检查。当前缓存 `windows-installer/cache/integration/desktop-hdr/accepted-runtime.tar` 是旧编译包，不能视作修复完成。Windows `prepare-integration.py`、维护 `prepare_payload.py` 和最终 `make-development-package.ps1` 现在都会拒绝缺少新标记、仍含 DMI/OP3 门禁字符串或 KWin 的 `libkwin.so.6` / `libkwin.so` 未指向已校验 `.6.7.3` 二进制的缓存；安装器打包还会检查复制后的暂存归档。尚未重编固定版本 KWin 和前端，因此该 HDR 运行时也阻塞后续完整安装包。已接受的旧 OP3 桌面画面不能替代 X2mini 实机验收。

已完成两轮独立审查，修正无条件输入匹配和 CRLF 模板处理问题。源码单测、离线 Linux 夹具及构建前拒绝旧模块测试见 `work/model-compat-20261021/`。没有做新装、维护实机升级、重启或休眠验收。

| 交付项 | 状态 |
| --- | --- |
| 1. 更新列表与验收记录 | 完成：本候选记录及维护记录；最终测试计数见 verification.json。 |
| 2. 新装脚本、组件清单、维护入口同步 | 完成源码同步：prepare-integration、维护规划与 prepare_payload；中文/英文 gyro 选项移除固定 BIOS 文案；无新增选项或 ID，maintenance-options 专用项无须变更。维护应用已重新生成 38 文件并核对 manifest、公钥及源码字节。最终载荷阻塞：旧 gyro 模块必须重编，固定 KWin/HDR 前端运行时也必须重编；安装器和维护准备入口均拒绝旧二进制，最终打包入口检查源和暂存归档。未从含未公开 CPU 开发源码的根缓存生成分发包。 |
| 3. 版本与标识 | 完成：本地候选沿用 1.0.6，不覆盖既有版本/附件，尚未分配发行修订。 |
| 4. 针对性验证 | 原源码/离线夹具见 verification.json；本次 HDR 归档策略 12 项、Windows 准备前阻断 2 项、维护载荷准备 20 项、PowerShell 合成归档及最终打包策略检查通过。主机无 `g++`、`clang++` 或 `cl`，C++ 策略单测和固定版本 KWin/前端均未编译；BMI260 模块构建及两机实测仍阻塞，不能替代实机验收。 |
| 5. 维护器签名 Release | 阻塞：精确内核模块与 EDID-only 固定 KWin/HDR 前端均未重建，未签名或发布。后续使用正式密钥 status/preflight/prepare 从隔离公开基线重新准备。 |
| 6. 公开下载与实机升级 | 阻塞：没有本轮正式产物；仍需最终签名产物公开下载验签、两机升级/重启及必要恢复。 |
| 7. Windows 完整安装包与 Release | 阻塞：等待两个运行时重建及维护验收；未构建或发布完整 PublicRelease 包。不得直接打包根工作区的未公开 CPU/研究代码。 |
| 8. README 版本号 | 不适用：版本未变，本轮未改 README。 |
| 9. 交付核销 | 完成已做/未做边界记录；本分支仍是未提交的工作区候选，不是完成发布。 |

InputPlumber 匹配和搜索路径依据固定版本的[官方匹配源码](https://raw.githubusercontent.com/ShadowBlip/InputPlumber/v0.78.0/src/config/mod.rs)及[搜索路径源码](https://raw.githubusercontent.com/ShadowBlip/InputPlumber/v0.78.0/src/config/path.rs)核对。
