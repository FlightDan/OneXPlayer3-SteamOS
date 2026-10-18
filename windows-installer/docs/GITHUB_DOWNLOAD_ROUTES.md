# GitHub 下载线路

维护器从 `1.0.6+maintenance.1` 起默认先访问官方 GitHub，遇到连接或服务错误时尝试备用线路。可在“设置 → GitHub 下载线路”选择自动、官方直连或指定线路。此设置用于公开项目资源；Valve 系统镜像仍使用自己的下载来源。

| 选项 | 用途与本次测试边界 |
| --- | --- |
| 自动（默认） | 官方优先，失败后尝试备用线路 |
| 官方直连 | 只访问 GitHub 官方端点 |
| gh-proxy.com | 发布 API、签名目录、完整维护核心验证通过；大 Windows 包本次忽略 Range |
| ghfast.top | 签名目录、完整维护核心验证通过；大附件开始位置 Range 通过 |
| ghproxy.net | 签名目录、完整维护核心验证通过；大附件开始位置 Range 通过 |

以上是 2026-10-18 本机网络出口结果，不是中国大陆测速或长期可用性保证。下载仍须通过正式签名和哈希核验。文件传输中断或核验失败时，请切换线路后重试。

## 维护安装入口

以下地址指向相同版本的 Bash 安装入口。首次下载应从可信项目来源核对发布公钥及校验值。

- [官方入口](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6%2Bmaintenance.1/install-oxp3-maintenance.sh)
- [GH-Proxy 入口](https://gh-proxy.com/https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6%2Bmaintenance.1/install-oxp3-maintenance.sh)
- [ghfast 入口](https://ghfast.top/https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6%2Bmaintenance.1/install-oxp3-maintenance.sh)
- [ghproxy.net 入口](https://ghproxy.net/https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6%2Bmaintenance.1/install-oxp3-maintenance.sh)

下载后在 SteamOS 桌面以普通用户运行：

```bash
bash install-oxp3-maintenance.sh --github-network auto
```

将 `auto` 改为 `direct`、`gh-proxy.com`、`ghfast.top` 或 `ghproxy.net` 可指定线路。选线会传给打开的维护界面；在设置中保存后供后续启动和定时检查使用。

## Windows 完整安装包

从对应 Windows Release 复制完整 ZIP 的官方链接，可在前面加上 `https://ghfast.top/`、`https://ghproxy.net/` 或 `https://gh-proxy.com/` 使用相应线路。例如公开 1.0.5 的完整包：

- [ghfast 下载 1.0.5](https://ghfast.top/https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/v1.0.5/oxp3-steamos-installer-1.0.5-20261018-140045.zip)
- [ghproxy.net 下载 1.0.5](https://ghproxy.net/https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/v1.0.5/oxp3-steamos-installer-1.0.5-20261018-140045.zip)
- [GH-Proxy 下载 1.0.5](https://gh-proxy.com/https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/v1.0.5/oxp3-steamos-installer-1.0.5-20261018-140045.zip)

此处的 1.0.5 仅为已公开链接示例，不含新增体检功能。新完整包的链接以相应 Release 为准；下载后核对该 Release 的 SHA-256，不要只以网页能打开判断安装包完整。
