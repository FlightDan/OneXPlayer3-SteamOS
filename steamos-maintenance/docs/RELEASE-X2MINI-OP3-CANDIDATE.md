# X2mini / OP3 兼容分支候选（未发布）

日期：2026-10-21；分支 `release/x2mini-op3-compat`，整合版本仍为 1.0.6。

维护安装入口和适配策略不再根据 DMI 厂商/产品名拒绝；DMI 缺失也不阻断系统探测。保留系统、内核、软件与实际资源检查。gyro 不再以 BIOS 字符串作为入口条件，底层包装驱动源码改为检查真实芯片，最终模块尚未重编。

维护部署会在 input 的同一文件事务中携带运行时 profile helper 和 InputPlumber 启动 drop-in；原版精确机型块可在运行时副本中转换，用户校准与原配置保持。完整实现、测试边界及根目录九项交付核销见 [安装器兼容候选记录](../../windows-installer/docs/RELEASE_X2MINI_OP3_COMPAT_CANDIDATE.md)。

复核又发现固定 KWin 桌面 HDR 运行时仍带 OP3 DMI 硬拒绝。源码已改为保留内部屏幕及 SDC4301 EDID 检查，并同步增加旧归档拒绝逻辑；当前缓存二进制尚未重编。维护 `prepare_payload.py` 会在创建载荷暂存目录前拒绝旧的 `accepted-runtime.tar`，并确认加载入口 `libkwin.so.6` 和 `libkwin.so` 都解析到已校验的 `.6.7.3` 二进制；最终 Windows 打包脚本也会在输出创建前和缓存复制后各检查一次。

完成：源码入口同步、独立审查、针对性维护测试、38 文件维护应用重新生成及一致性检查。无新增维护选项或组件 ID，无须调整维护专用选项。

阻塞：对应内核 headers/Module.symvers 和完整构建工具链缺失，不能提供已重建 BMI260 模块；固定 KWin 与 HDR 前端也尚未按 EDID-only 策略重编。prepare_payload 会拒绝旧模块和旧 KWin 归档；没有执行正式签名、维护 Release、公开下载验证、实机升级或 Windows 完整包发布。后续须以隔离公开基线重新准备，继续排除未获准公开的动态功耗研究/CPU 开发载荷，沿用正式公钥和签名流程。

不适用：版本未变，README 未修改；本轮未请求设备操作。
