# BMI260 陀螺仪

2026-10-13，按“测试陀螺仪漂移”会话 01a1349b-8017-7783-9d68-441f3757de2e 的实测结果纳入安装资源，并进入此前完整测试包。当前包与源码差异以 [README](../README.md) 为准。

用户已确认游戏内跟随正常、方向正确；该设备的静止校准通过。长期温漂、重启、休眠唤醒和新安装后的完整恢复仍待实机测试。这些结论不等于新安装器已经通过掌机验收。

安装器提供独立、默认开启的 gyro 选项，依赖背键/input 基础配置。加载范围严格限定 ONE-NETBOOK / ONEXPLAYER 3、BIOS 5.09、SteamOS 3.10 build 20260924.1000、内核 7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9、InputPlumber 0.78.0。专用 I2C 包装模块使用系统已有 bmi270_core 与 BMI260 固件，不修改 ACPI 表或引导器，不执行 HID 重新绑定。

专用 InputPlumber 放在 /var/lib/oxp3-gyro-v1，系统 /usr/bin/inputplumber 保留。启动时专用驱动或版本条件不满足则回退系统 InputPlumber。49-onexplayer_3-gyro.yaml 使用已验证的 400 Hz 采样和安装矩阵；它排序在 50-onexplayer_3.yaml 基础配置之前，恢复时移除独立文件，保留背键及 R5 映射。InputPlumber 0.78 的目录排序实现见 https://github.com/ShadowBlip/InputPlumber/blob/v0.78.0/src/config/path.rs 。

新安装的 gyro_bias 为 [0, 0, 0]，关闭动态零偏和人工回正。不携带研究设备的测量记录或固定零偏；每台设备需要重新静置校准，并在 Steam 中核验游戏方向与漂移。研究脚本绑定特定测量文件与恢复清单，不能直接在新安装上照搬执行。

恢复入口为 sudo python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py restore --component gyro。恢复会先停止 InputPlumber、卸载专用模块，恢复文件后重新加载服务定义并启动原先运行的 InputPlumber。任一文件有用户修改（包括后续写入的设备校准），会先拒绝整组恢复，避免只移除启动脚本而留下引用它的服务；应先保存并处理修改。

资源来源：

- 私有模块源码：research/gyro/oxp3_bmi260.c、bmi270.h、onexplayer3-bmi260.patch、Makefile；保留 SPDX GPL-2.0-only OR BSD-2-Clause。
- 专用 InputPlumber 二进制：上游 v1.6.1 oxp3-fix.tar.gz 中的 inputplumber-oxp3-gyro，https://github.com/HHHHanasak1/onexplayer3-steamos-setup/releases/tag/v1.6.1 。只提取此二进制，未执行旧版 ACPI 安装脚本。
- 对应 InputPlumber 0.78.0 补丁与许可证随 cache/integration/sources/gyro 保存。InputPlumber 来源 https://github.com/ShadowBlip/InputPlumber/tree/v0.78.0 。
