# Split-lock 报告修复（0.1.4 开发分支）

来源为 kas5852 的 [上游 PR #16](https://github.com/HHHHanasak1/onexplayer3-steamos-setup/pull/16)
及 [20261015 修复包](https://github.com/HHHHanasak1/onexplayer3-steamos-setup/commit/8e4d2fb3772ce85355a1300c7fb3b51fa603f796)。
保留 Copyright (c) 2026 HANA & Claude 和完整 [MIT 许可证](UPSTREAM_LICENSE)。
本项目适配引导事务和保守清理逻辑，由 FlightDan 维护。

## 安装与恢复

安装器和维护工具提供默认选中的独立 `split-lock` 修复，限定现有已验证的
ONEXPLAYER 3 / SteamOS 3.10 build 20260924.1000 / 精确 7.2.4 内核。
只在 Valve 内核入口添加 `split_lock_detect=off`，并保存对应 grub.d 配置；保留其他参数，
拒绝冲突设置和不支持的引导语法。需要正常重启后才生效。

GM7 修复与本项同时安装时，由单一事务所有者保存组合后的 EFI GRUB 文件和真正的原始文件，
避免两个独立原始快照相互覆盖。安装器恢复时明确使用 `--component boot-repairs`；
维护工具须同时选择 `gm7-resume` 与 `split-lock` 恢复。部分恢复会在写入前拒绝。
恢复只针对本项目文件事务，不会重新生成或清理其他管理员设置。

关闭检测后不再报告 split-lock 指令。是否有性能收益取决于实际工作负载，
不能将上游的 CPU 使用率直接当作本机结果。游戏、Steam 客户端和官方系统更新策略保持原有配置。

## 已有报告的精确清理

新装和维护安装只部署引导修复，**不隐式删除已有报告**。管理员确认参数已在当前内核命令行
生效后，可使用安装器附带的 `split_lock.py cleanup` 显式清理固定报告目录。
清理只接受 JSON 顶层 `type` 精确为 `split_lock` 的普通单链接文件。
其他报告、无效 JSON、重复 JSON 键、NaN/Infinity、二进制、符号链接和过大文件均保留。
目录及文件须归 root 或核实的非登录 SteamOS 日志服务账户所有，且不能供组或其他用户写入。
不修改目录所有权或降低权限。

实机清理暂停报告提交服务，并为保留文件的路径、内容与元数据计算前后摘要；
无论成功与否均恢复服务。Linux 文件描述符和 `O_NOFOLLOW` 限制目录遍历，
读取和删除前核对 inode、大小、时间和硬链接数。

## 2026-10-16 实机记录

- 通过原有严格 SSH 指纹校验，普通重启后确认 `split_lock_detect=off` 生效。
- 清理前 316,757 个文件中，311,510 个明确属于 split-lock；已全部清除，释放
  1,275,944,960 字节实际分配空间（约 1.19 GiB）。
- 其他 5,247 个文件全部保留，前后内容与元数据摘要完全一致；报告服务已恢复。
- 额外 CPU 短采样没有测到持续开销，不能声称本次修复带来已验证的帧率提升。

本地证据：`research/evidence/split-lock-cleanup-final-20261016.txt`；
实机私有备份与恢复程序：`/var/lib/oxp3-split-lock-20261016/`。
这次实机适配验证不代表完整全新安装/OOBE、长期游戏或所有 BIOS/内核均已验收。
