# 0.1.4 发布准备

状态：`0.1.4+maintenance.2` 已公开，22 个附件匿名下载与签名核验通过，实机已完成受控恢复及 26 项组件应用。正常重启发现 TDP 启动检查与用户遥测服务检查问题，修订 3 一并修复，并解决概览版本缓存；发布及重启复验按最终记录更新。对外项目版本统一为 0.1.4，签名包和下载标签保留内部修订号；已公开资产不覆盖。Windows 0.1.3 仍为 Latest，Windows 0.1.4 等待实机升级验收。

## 0.1.4 维护更新内容

- **中文界面**：按 KDE 翻译语言选择维护窗口语言，兼容英文区域格式与简体中文界面并用；修正操作确认区域未显示的问题。
- **CPU 功耗**：提供 PL1 / PL2 控制与 Steam TDP 同步，保留 EPP 和核心分组限频。
- **Split-lock**：通过当前槽位事务添加启动参数，重启后生效；支持冲突检测和恢复，不自动清理已有报告。
- **OXP3 Light**：三分区纯色、亮度和开关；旧 HID 协议不支持状态读回，不自动重放开机或休眠后的设置。
- **串口重复报错**：新增 `serial-console-policy` 维护组件，用条件 drop-in 阻止默认不可用的串口登录服务；保留内核控制台，`oxp3.serial-console=1` 可显式启用。当前槽位的应用、收据和恢复已通过隔离 Linux 测试；系统重启后生效。
- **AutoFlatpaks 电池状态**：可选 `autoflatpaks-compat` 只修复用户已安装且精确匹配的 1.6.8，更新为 1.6.8+oxp3.1。仅写入前端和版本元数据，保留设置、后端及许可证；未知或修改过的版本拒绝处理。未安装插件时不安装完整插件。修改后需新会话或重启。
- **Opti2XMX**：独立插件版本 0.2.4，帧生成控件保留实验标记。Cyberpunk 2077 2.31 在已记录的 Proton/驱动环境、关闭光线追踪时，2x / 3x / 4x 的实际帧呈现已验证；不能推及其他游戏或光追稳定性。RT Ultra 的 GPU timeout/device lost 在恢复原游戏后仍可重现，不计为通过。

已有实机组件测试与本次正式安装链路验收分别记录。当前设备串口与 AutoFlatpaks 热修复观察 336 秒无新增对应错误；正式公开入口的 0.1.3 → 0.1.4 升级将在维护 Release 发布后执行。详见 [验证记录](../VALIDATION.md) 和 [组件验收](../../windows-installer/docs/RELEASE_0.1.4.md)。

## 分组

| 产物 | 仓库 | 内容 |
| --- | --- | --- |
| 维护入口与常用修复 | OneXPlayer3-SteamOS | 原生窗口、升级/恢复工具、完整清单、体积小的修复 |
| 大型驱动/运行库 | OneXPlayer3-SteamOS | Decky、WiFi、陀螺仪、桌面 HDR、管理器、Waydroid 分别打包 |
| 本项目插件 | OneXPlayer3-SteamOS | 风扇、CPU、充电、灯光、重启 Windows 各自独立包 |
| Opti2XMX 插件 | Opti2XMX | 轻量插件及 XMX 运行库下载界面；不内嵌运行库 |
| 可选 XMX 运行库 | Opti2XMX | ANV 驱动、igdext64、IGC/ocloc、XeSS SDK DLL、辅助脚本及声明；不含 OptiScaler |

第三方现成插件不分发，用户自行安装。旧安装的第三方插件不会因升级而删除。仅更新 Opti2XMX 插件不移除用户已有的 XMX 运行库。

2026-10-16 本地完整 QA 实包体积如下，重建时会随源码变化；首次还未安装 Decky 的用户选择插件时，需同时下载 Decky 依赖。

| 资源 | 压缩下载体积 |
| --- | ---: |
| 一键 Bash 入口 | 122.5 KiB |
| 维护入口与常用修复 | 871.0 KiB |
| Decky | 24.72 MiB |
| 桌面 HDR | 12.11 MiB |
| Waydroid 宿主组件，不含 Android 镜像 | 6.55 MiB |
| 管理器 | 4.78 MiB |
| WiFi | 4.67 MiB |
| 陀螺仪 | 4.03 MiB |
| 风扇 / CPU / 充电 / Windows 重启插件 | 4.6 / 10.8 / 5.2 / 23.1 KiB |
| Opti2XMX 独立 Decky ZIP / 维护器组件分片 | 65.1 / 127.7 KiB |
| XMX 原始运行库 / 维护器外层分片 | 186.4 / 184.9 MiB |

完整清单引用组件分片；独立 Opti 按钮下载原始运行库，两者不可混用。Opti ZIP 不含运行库。清单和签名等小型辅助文件不计入上表。

## 输入与生成

1. 在目标 0.1.4 分支完成所有组件修改、缓存刷新及验证后，用 `prepare_payload.py` 生成新的完整输入。不要把旧 QA 载荷当作最终 0.1.4 的 CPU/功耗实现。
2. 在 Opti2XMX 独立分支构建前端，并通过 `package_plugin.py` 生成独立 ZIP。最终 `runtime-source.json` 固定引用已发布 v0.2.3 的原始运行库，校验大小与 SHA-256；本次独立 ZIP 保留实验版本号。
3. 用本目录中跟踪的版本声明及独立插件 ZIP 生成发布载荷，保持输入不变：

```bash
python3 prepare_release.py --payload /work/prepared-current \
  --release-metadata release/0.1.4.json \
  --opti-plugin /work/opti2xmx/opti2xmx-VERSION.zip \
  --opti-runtime /work/opti2xmx/published-runtime.tar.gz \
  --output /work/prepared-0.1.4
```

4. 使用真实发布公钥/私钥运行独立打包流程的 modular 模式。目录必须全新，密钥不放入输入源码或载荷。以前已发布过拆包清单时，传入旧清单和签名；打包器仅在内容完全相同且来源符合要求时沿用旧 Release 地址。最新清单始终完整，不能只提交本次变化的插件条目。

输出分为 `maintenance/` 与 `opti2xmx/`，`release-plan.json` 列出预期 Tag、资产地址、新包和复用包。正式发布时，先确保所有引用的附件可下载，再开放维护清单；保留旧清单引用的附件。维护 Release 发布后执行公开下载验证及实机升级；Windows 0.1.4 安装包在实机升级验证后发布。

```bash
python3 package_release.py --modular --payload /work/prepared-0.1.4 \
  --source /work/steamos-maintenance \
  --public-key /secure/publisher-public.pem \
  --private-key /secure/publisher-private.pem \
  --output-dir /work/release-0.1.4 \
  --tag maintenance-v0.1.4 --opti-tag maintenance-assets-v0.1.4
```

## 旧版直接升级

使用最新的一键 Bash 入口。它先验证小型 schema-1 引导包。已有旧维护程序时，界面先让用户确认仅升级维护程序，再继续原来选择的组件。新程序根据完整清单和依赖关系从各个 Release 获取组件，不需要依次安装历史版本。

旧版脚本可能不识别独立 `maintenance-v` Tag；首次切换时应提供最新 Bash 入口链接，不能声称未更新过的旧脚本自动获得新协议。组件安装记录按系统槽分别保存，更新维护程序不会把旧组件误标为已更新。恢复组件原状时，其安装记录随事务一并清除。
