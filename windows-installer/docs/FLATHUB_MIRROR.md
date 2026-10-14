# SteamOS 桌面模式应用商店：中科大 Flathub 源

选项 ID 为 `flathub-ustc`，当前界面显示“SteamOS 桌面模式 应用商店 · 中科大 Flathub 源（可选）”。中文界面初始开启、英文初始关闭；手动选择后，切换语言不再改变选择。此选项独立于 AutoFlatpaks，只处理 Flathub，不改 SteamOS 更新、pacman、Steam 下载地区或其他 remote。

## 当前执行与恢复

`components/integration.py` 已接入目标镜像内的**系统级** `var/lib/flatpak/repo/config`：要求已有 `[remote "flathub"]`，修改其 URL 为 `https://mirrors.ustc.edu.cn/flathub`，通过组件文件事务保留原配置。未选择时不修改；缺少现有 remote 时报告未安装，不隐式新增源。

重复应用保留首次原件，恢复按事务记录核对当前文件，用户修改冲突时拒绝覆盖。用户级 remote 的自动发现与双作用域统一管理仍未接入；不要把本选项理解为已经处理所有用户和系统 Flathub 配置。`components/catalog.json` 的旧研究状态不是实际执行入口，当前行为以集成代码和组件结果为准。

组件文件配置完成不等于 Discover 刷新、联网安装或真实应用下载已经通过；新装桌面模式仍需单独验收。

## 已有证据与待验

2026-10-13 本地曾探测元数据端点 `summary.idx` 返回 HTTP 200，该记录只说明当时可连接，不保证当前连接或应用下载成功。

镜像可能在未命中缓存时访问上游，应用的 extra-data 也可能从厂商站点下载。相关说明见 [中科大镜像帮助](https://mirrors.ustc.edu.cn/help/flathub.html) 和 [Flatpak 命令参考](https://docs.flatpak.org/en/latest/flatpak-command-reference.html)。

待验项目包括新装 Discover 加载与实际下载、离线错误、用户级 remote，以及已有用户配置的恢复冲突。选项和组件部署范围见 [组件说明](COMPONENT_INTEGRATION.md)。
