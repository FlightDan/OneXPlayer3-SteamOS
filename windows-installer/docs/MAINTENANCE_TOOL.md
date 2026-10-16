# KDE 桌面维护工具集成

`codex/0.1.4` 的镜像准备默认内置现有 GTK 3 维护工具。无论用户是否勾选修复或插件，A/B 两槽都安装程序本体，共享 home 中提供可执行、deck 所有的桌面及应用菜单入口：

- `~/Desktop/OXP3-Maintenance.desktop`
- `~/.local/share/applications/OXP3-Maintenance.desktop`

入口以桌面用户执行 `/usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py gui`，直接打开原生触屏窗口。真正安装修复仍沿用窗口审核、pkexec 认证和后端验签。

## 内置范围

只准备 `entry.py`、`OXP3-Maintenance.desktop`、`oxp3_maintenance/*.py` 和发行者提供的 `trusted-public-key.pem`。不复制测试、缓存、驱动、插件、XMX 运行库、完整维护包或 shell 下载入口。当前无公钥的开发暂存为 25 个文件、413354 字节；后续源码变化以准备报告为准。

复用维护工具自身的 `runtime_files()` 生成固定入口、按内容哈希区分的程序目录、实际发行元数据和空激活记录。离线读取只针对目标镜像，绝不读取构建主机已安装的维护工具。桌面名称跟随安装器语言；程序目录内的原始文件不参与本地化，以保持生成哈希一致。文件沿用安装器的每槽和共享 home 事务备份及恢复流程。

维护工具的激活服务和每日检查单元随程序提供，本次离线集成不启用它们、不创建维护事务。原有首次启动服务继续负责安装器所选修复。后续用户通过维护工具安装或更新时，沿用其已有启用流程。

## 构建

在项目根目录运行系统 Python（或工作区可用的 Python）：

```powershell
python windows-installer/scripts/prepare-maintenance.py
python windows-installer/scripts/prepare-maintenance.py --check
& windows-installer/scripts/check-maintenance.ps1
```

默认输出 `windows-installer/cache/maintenance`。重新准备时先将旧暂存目录重命名留存，再生成新目录；命令不删除旧目录。安装器将此目录复制进 Linux 准备载荷，预检哈希后写入镜像。打包命令检查暂存文件与当前规范源码一致，拒绝遗漏、额外或过期文件。源码导出包含相同的维护程序源码集，可重新准备。

正式打包必须先由发行者配置真实 Ed25519 公钥 `steamos-maintenance/trusted-public-key.pem`，重新暂存并通过：

```powershell
python windows-installer/scripts/prepare-maintenance.py --check --require-key
& windows-installer/scripts/check-maintenance.ps1 -RequireKey
```

`make-development-package.ps1 -PublicRelease` 强制执行该检查。当前仓库未配置生产公钥；开发构建可打开程序窗口，但下载、离线导入和授权安装会因缺少可信公钥停止。不要发布无公钥镜像，也不要用 QA 公钥替代生产信任配置；已有无公钥开发安装无法通过 Bash 安装入口补设信任锚。

## 验证范围

`--cli maintenance-tool-checks` 在隔离 QEMU Linux 中测试双槽/重复准备、CLI 加载、快捷方式权限、回退、修改清单拒绝、缺少程序时写入前拒绝。相关共享存储、更新保护和运行文件访问回归由现有测试套件覆盖。`integration-verify.py` 另行核对实际镜像两槽中的文件、桌面用户读取权限、入口和系统 PyGObject/GTK 3 导入。

隔离目录测试不等同于 KDE 实际点击或完整新安装验收；正式镜像仍需桌面会话实测。

2026-10-16 本次验证：Windows 构建 0 警告/0 错误；组件结果与共享存储 C# 检查通过；隔离 Linux 的维护专项 5 项、共享存储 22 项、更新保护 3 项及运行权限 3 项通过；运行库生成的 9 项纯逻辑测试（Windows 使用 fcntl 导入替身）与准备边界 3 项通过。正式打包缺少公钥时在创建输出前拒绝。记录见本地 `windows-installer/logs/maintenance-tool-integration-20261016.json`。
