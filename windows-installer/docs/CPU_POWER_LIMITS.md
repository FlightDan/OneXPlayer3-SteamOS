# OXP3 CPU 功耗限制检查

检查分支：`codex/0.1.4`。实机读取时间：2026-10-16 00:02:55 +08:00。

## 实机结果

设备为 ONEXPLAYER 3，Intel Arc G3 Extreme，BIOS 5.09（08/10/2026），内核 `7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9`。检查时接电，电池状态 Full。

| 接口 | PL1 / long_term | PL2 / short_term |
| --- | --- | --- |
| `/sys/class/powercap/intel-rapl:0`（MSR） | 40,000,000 µW = 40W | 40,000,000 µW = 40W |
| `/sys/class/powercap/intel-rapl-mmio:0`（MMIO） | 40,000,000 µW = 40W | 40,000,000 µW = 40W |

两路 `enabled=1`。后续再次读取，四项仍均为 40W。这些是配置限值，不是实测耗电；本次没有运行负载测试。

本次启动日志给出了限制变化来源：

- 2026-10-15 23:16:03 +08:00，RAPL provider 启动快照为 MSR PL1 25W、MMIO PL1 35W，**两路 PL2 都为 52W**。
- 23:16:10 开始，provider 记录接受 40W 请求，双路 PL1、PL2 均读回 40W；23:52:41 仍有同样请求。
- `oxp3-rapl.service` active，旧 `oxp3-tdp-sync.service` inactive。

因此，当前 PL2 被软件设置为 **40W**。用户看到的 BIOS 51W 尚未直接核对 BIOS 页面；本次启动时 Linux 实际读到的是 52W，不能将二者直接认定为相同值或断言差异原因。

## 新滑块实现前的软件策略（历史检查）

运行中的 `/var/lib/oxp3-rapl/provider.py`、维护源码 `research/rapl/provider.py`、controls r5 ZIP 内源码及 `cache/integration/native-tdp/000.bin` 的相关策略一致：

- 设置 TDP 10–35W：两个 PL1 设为请求值，两个 PL2 分别降至原值与 35W 的较小值；已有更低限制继续保留。
- 设置 TDP 36–40W：双路 PL1、PL2 均设为请求值，最高 40W。
- provider 启动只读取快照；收到设置请求才写入。成功设置后不会自动恢复原来的 52W PL2，事务失败才尝试回滚。
- 原生 TDP getter 显示两路 PL1 中较低的值，不能据此单独确认 PL2。

## Intel 80W 的含义

[Intel 官方 G3 Extreme 规格](https://www.intel.com/content/www/us/en/products/sku/245625/intel-arc-g3-extreme-processor-12m-cache-up-to-4-70-ghz/specifications.html)列出 Processor Base Power 25W、Maximum Turbo Power 80W。80W 是处理器规格中的最大睿频功耗，不证明这台整机当前设为 80W；[Intel 数据表](https://cdrdv2-public.intel.com/872188/872188-001.pdf)说明最大睿频功耗可由系统厂商配置。

这次检查发现的三个不同层次是：Intel 标称 80W、provider 启动时两路 PL2 52W、当前软件设置后的两路 PL2 40W。PL2 是 package 功耗限制，不能当作独立 CPU 核心功耗额度。

以上首次检查仅只读。后续经用户明确授权，另行完成下面的临时写入测试；没有修改 BIOS 或永久功耗策略。

## 52W / 80W PL2 临时写入测试

2026-10-16 00:07:27–00:07:37 +08:00，在同一设备、同次启动中测试。只写两个 `constraint_1_power_limit_uw`，PL1 全程保持 40W；没有启动游戏、压力程序或其他负载。

| PL2 目标 | MSR 即时读回 | MMIO 即时读回 | 1 / 3 / 5 秒采样 | 每轮恢复 |
| --- | --- | --- | --- | --- |
| 52W | 52W | 52W | 两路均保持 52W | 两路均恢复 40W |
| 80W | 80W | 80W | 两路均保持 80W | 两路均恢复 40W |

`oxp3-pl2-probe-20261016-a1.service` 运行结果 success，主程序及独立 `ExecStopPost` 恢复均验证通过。00:08:18 再次独立读取：双路 enabled=1、PL1=40W、PL2=40W，原 `oxp3-rapl.service` 仍 active。

结论：在本次条件下，**52W 和 80W 都可通过 Linux RAPL 接口写入并在 5 秒采样窗口内保持**。80W 没有被接口直接拒绝或立即钳到启动时的 52W；这不能证明实际负载能达到 80W，也不能证明热稳定性、性能提升、重启保持或再次移动 TDP 滑块后的保持。当前 TDP setter 仍会按上面的软件策略覆盖 PL2。

回滚与证据保存在设备 `/var/lib/oxp3-pl2-probe-20261016-a1/`（root 私有目录）；本地测试源码为 `research/tools/pl2-write-probe-20261016.py`，输出为 `research/evidence/pl2-write-probe-20261016.txt` 和 `pl2-write-probe-final-20261016.txt`。脚本逐轮恢复原值，systemd 超时与独立结束恢复覆盖主进程异常退出。未启动永久服务。

## 是否独立开放 PL2

用户确认指的是 Steam 原生单个 TDP 滑块。它通过 `TdpLimit1.TdpLimit` 单一数值调用当前设备的 RAPL provider，**不只影响 PL1**：10–35W 时同时钳制 PL2 至不高于 35W，36–40W 时让 PL1=PL2。Steam 当前界面没有单独的 PL2 控制。

独立 PL2 作为高级选项有价值：可以保留持续功耗 PL1，同时为短时突发保留更高功耗上限。当前 40W 设置使 PL1=PL2=40W，软件层面没有额外的 52W/80W 突发余量。

[Intel 控制接口文档](https://intel.github.io/drivers.gpu.control-library/Control/api.html#ctl-power-burst-limit-t)说明 PL1 约束较长窗口的平均功率，PL2 约束较短窗口的突发功率；频率还可能受温度、电流和软件频率范围约束。基于这一机制，预期收益更可能出现在短时 CPU 峰值、间歇性负载、部分 CPU 受限场景；持续游戏仍可能受 PL1、GPU、温度等因素限制。不能承诺平均帧率或低帧表现显著提升，也不能把 52→80W 的限值比例当作性能增长比例。本次没有做性能对照测试。

建议保留简易 TDP 控制，将独立 PL2 置于高级选项，明确显示实时 PL1/PL2 与联动状态；保持现有默认行为，先把 52W 作为对照测试候选，80W 暂作为实验设置。若实现独立 PL2，需要同时修改原生 TDP setter，避免调整 PL1 时覆盖 PL2，并由同一控制器负责双路事务和恢复。独立控制仍应约束 PL2 不低于 PL1，且处理 AC/DC、休眠恢复和按游戏配置的状态同步。

## 0.1.4 分支：OXP3 CPU 独立功耗滑块

根据后续用户要求，OXP3 CPU 0.2.0 增加 PL1（10–40W）与 PL2（最高 80W）两个滑块。插件主动修改 PL1 时，调用 Steam 原生滑块使用的统一设置接口，更新 `steamos_tdp_limit` 并启用 `steamos_tdp_limit_enabled`，等待原生状态确认后通过同一 D-Bus 属性核对硬件。旧 `SystemPerfStore` 中的 per-app TDP 字段不代表当前原生页面的数值。插件轮询当前硬件值，服务沿用现有失效通知链。PL2 通过同一个 RAPL 服务独立设置；PL1 降低时不再压低 PL2，PL1 超过某路 PL2 时只将该路抬至 PL1。PL2 起点跟随任一路 PL1 的最高值。

源码已纳入 `components/controls/cpu/` 与 `components/controls/rapl/`，安装器和 controls r6 资源包使用同一来源。两路写入与回滚由单个控制器串行处理，失败只回滚本次尝试过的路径，保留未写入路径的外部变更。页面显示实时双路值、待写入/写入中/失败状态，卸载会取消尚未执行的界面请求。

没有新增开机、插件加载或重载时自动提高功耗的行为。主动调整 PL1 使用 Steam 自身的设置保存机制；PL2 仅为运行时硬件状态，没有新增每游戏、AC/DC 或跨重启的 PL2 配置。原有频率/EPP 恢复按钮仍只负责频率/EPP。

本地事务、适配器和界面交互测试及独立审查已完成。用户说明临时启动了 Windows，返回 SteamOS 后原信任记录恢复匹配；没有更换主机信任密钥。新版 provider、CPU 插件已部署，备份和恢复入口位于设备 `/var/lib/oxp3-cpu-power-update-20261016-a2/`。

实机滑块验收通过：插件 PL1 调到 20W，Steam 性能页面显示 20W、双路硬件读回 20W；Steam 原生滑块调到 30W，插件显示 30W、PL2 起点跟随至 30W，PL2 仍为 52W。直接操作 PL2 滑块到 52W 和 80W，两路硬件均写入成功，没有 Python exception，PL1 和 Steam 设置保持不变。适配器显式传递 `dbus.UInt32`，修复此前 D-Bus 参数类型导致的写入失败；Decky 冻结 Python 环境通过系统 Python 子进程访问 D-Bus。

界面实测两行瓦数均为字重 700、右边缘一致；51W 保持普通颜色，52W 起黄色。实机截图 `research/evidence/cpu-power-40-52.png` 展示 PL1 40W、PL2 52W。验收输出分别为 `cpu-power-native-ui-final-20261016.txt`、`cpu-power-pl2-slider-final-20261016.txt`。测试结束已恢复测试前 PL1 40W / PL2 49W 和 Steam 原生 40W，未运行负载或性能对照。
