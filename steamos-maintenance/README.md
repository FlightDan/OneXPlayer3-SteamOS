# OXP3 修复与项目更新工具

面向已经安装旧版项目或其他版本 SteamOS 的 ONEXPLAYER 3：发现最新项目能力，按需下载维护包，选择安装修复和插件。提供桌面原生触屏窗口及同一套命令行后端。

1.0.6 开发分支已将本工具的必要程序代码接入 Windows 安装器镜像准备，并提供 KDE 桌面及应用菜单入口。该入口直接打开现有 GTK 窗口，组件资源继续按需下载；正式镜像需预置发行公钥。详见[集成说明](../windows-installer/docs/MAINTENANCE_TOOL.md)。

**这里的更新仅指本项目。工具不会升级 SteamOS，不改变 Valve 官方系统更新的现有设置。** SteamOS 新版本的适配、升级和迁移不在本工具首版范围内。

1.0.6 提供正式签名维护包与 Bash 安装入口。已测范围与待测项见 [验证记录](VALIDATION.md)。源码目录不是可直接用于修复设备的发行包；不要把开发目录作为可信安装包提权运行。

## 支持范围

- 版本和功能发现不以已安装的维护工具版本为门槛；同版本也能浏览和添加尚未安装的选项。稳定版与 Beta 通道分别筛选，项目已有发布但缺少 Linux 维护包时会明确说明。
- 所有 OXP3 SteamOS 用户可浏览完整签名目录，先获取小型维护入口，再按勾选项及依赖下载组件。安装逐项预检：原生驱动、HDR、Decky 和插件运行库仍要求 SteamOS 3.10 / build `20260924.1000`、内核 `7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9`，并检查各组件的软件包和 BIOS 条件。陀螺仪要求 BIOS 5.09。
- 屏幕键盘和 Flathub 源采用独立的跨版本设置适配器，检查所需资源后可用于其他 OXP3 SteamOS 版本。其他版本不会套用当前内核驱动；未适配项显示原因，仍可下载维护包供以后使用。其他发行版、非 `deck` 桌面账户、多设备 Btrfs、LVM/加密映射根分区未提供写入适配器。
- 原版 SteamOS，以及有可信事务记录的本项目安装器安装。沿用安装器的组件 ID、准备载荷和兼容条件，使用独立的运行中系统适配路径。
- 当前槽位按实际根分区 PARTUUID 识别，支持 ext4 和经内核 sysfs 验证的单设备 Btrfs。另一槽仅只读检查，不回放 ext4/Btrfs 日志。跨版本设置及维护工具只要求另一槽确认为 SteamOS；原生共享载荷仍要求相同底座、内核及软件包。
- 目录列出全部项目选项，包括独立的 rEFInd、槽位切换和缺少适配器的新功能。独立操作不会被当成普通文件修复安装；新增适配器可先通过“仅更新维护工具”获取。
- 不调整分区、不部署 rEFInd、不配置账户密码或 SSH。GM7 修复仅在确认系统磁盘为对应 NVMe 后修改当前槽已有的启动配置。
- 未知 Decky、旧 HANA 脚本遗留和用户改动按组件报告冲突，不自动清理或覆盖。旧运行库原件不完整、存在无法表达的原件额外文件时拒绝接管，保留原恢复入口。
- 常用小修复与维护程序合在核心包；大型驱动/运行库、本项目插件独立打包。Opti2XMX 插件不默认下载 XMX 运行库，可另选 `opti2xmx-runtime`；第三方现成 Decky 插件由用户自行安装，升级保留已有安装。

## 普通用户使用

### 轻量一键入口

在 OXP3 的 SteamOS **桌面模式**下载并运行最新维护渠道的 `install-oxp3-maintenance.sh`。维护渠道使用独立 `maintenance-v` Tag，Windows 安装器仍保持 Latest。发布者会提供固定公钥指纹；首次使用需从可信项目来源取得脚本并核对该指纹。以下为 1.0.6 下载入口：

```bash
curl --fail --location --proto '=https' --proto-redir '=https' \
  --output install-oxp3-maintenance.sh \
  https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6%2Bmaintenance.1/install-oxp3-maintenance.sh \
  && bash install-oxp3-maintenance.sh
```

脚本内嵌验证代码和发行公钥，默认选择稳定版，先验证完整签名目录及小型核心包，再打开原生安装窗口。它以普通桌面用户运行，**不要加 sudo**；进入“修复与插件”选择项目后，按需获取缺少的组件和依赖，检查更改，确认后由系统认证执行安装。下载及已验证的组件缓存在 `~/Downloads/OXP3`，退出窗口后清理临时运行副本。已有旧维护后端时，先审核“仅更新维护工具”，再继续组件选择；工具升级不会把旧修复误记为已更新。安装后的更新核对原有公钥并拒绝降级；签名错误、缺包或网络失败会停止。

```bash
bash install-oxp3-maintenance.sh --channel beta
bash install-oxp3-maintenance.sh --version 1.2.3 --download-only
bash install-oxp3-maintenance.sh --bundle ./oxp3-maintenance-1.2.3-linux-x86_64.tar.gz
```

上面的 `1.2.3` 是版本示例，使用时替换为实际发行版本。`--download-only` 在模块发行中获取核心入口；需要离线安装的组件应提前用下文 CLI `download --select` 下载并组成可离线验签的选择包。打开安装窗口要求 OXP3 SteamOS、`deck` 桌面账户、GTK 3、Bash、Python 3 和 OpenSSL。脚本不自动安装这些系统依赖。

### 离线导入与组件选择

发布后，`oxp3-maintenance-<项目版本>-linux-x86_64.tar.gz` 是小型核心入口，保留完整功能目录以供选择。提前下载的组件选择包可以离线导入；发布者也可另外提供传统完整离线包。两者都应保留原归档及签名，在 SteamOS 桌面模式打开。

1. 首次使用，打开 `app/Install-OXP3-Maintenance.desktop`，按 KDE 提示允许执行。如被当成文本打开，先在“属性 → 权限”中允许执行；也可以运行 `app/oxp3-maintenance.sh`。首次安装应核对发行来源及随包公钥与项目公布的公钥一致。
2. 选择“浏览最新修复与插件”，先获取小型签名功能目录；可选择只下载，或下载后安装。最新目录始终列出全部组件及依赖，并可引用不同历史 Release 中未变化的附件。客户端按选择补齐缺包，无需依次安装中间版本。
3. 进入“修复与插件”，或导入已有维护包。系统认证后重新验证签名、环境、原安装记录和文件冲突。可信已安装项目默认隐藏，可用“显示已安装”开关查看；无法确认的项目仍显示。可用且未确认已安装的修复默认全选，插件按需点选。组件整行可点按，列表支持手指滚动。
4. 点击“检查更改”，核对项目版本、组件、自动加入的依赖及保留不动的旧组件后，在当前窗口确认应用。图形选择只刷新勾选项及依赖；取消勾选不会卸载已有组件。图形界面以普通桌面用户运行，修改通过系统认证交给后端。
5. 完成页区分文件安装、待重启及额外初始化。内核、显示、输入改动需要重启或新会话；工具不强制重启。首次陀螺仪校准和 Waydroid Android 镜像初始化仍需用户完成。
6. 后续从桌面或应用菜单打开“OXP3 修复与项目更新”。默认每日检查项目新版本，仅提示，确认后才下载和应用。可在设置中选择稳定/Beta 通道或关闭检查。网络失败、限流和缺包不会被显示为“已是最新”。

触屏窗口使用系统 Gtk 3 与 Python PyGObject；已在本次 SteamOS 实机确认可用。命令行、签名验证和事务后端不依赖图形库。界面在后台执行读取和网络请求，立即显示进度、连接重试和可读错误；状态页不再直接展示 JSON。详见 [界面约定](DESIGN.md)。

GitHub API 限流时会使用项目公开 Atom 发布源继续发现版本。发布源内容只用于提示；下载候选仍须通过已固定公钥验证签名目录。没有密钥、目录缺失或签名不匹配时会分别显示未知/待提供状态，不会从标签猜测可安装的下载包。

状态页分别报告受管组件、带备份的旧安装、只读观察到的外部插件及未知/不可读取记录。只有可信旧事务记录且当前文件验证一致才允许接管；缺少记录不会被当作全新系统。过时、缺包、不兼容及需单独处理的旧组件可保留原状，不阻塞其他独立选项。用户修改的风扇/CPU 设置、陀螺仪校准、Opti 游戏设置及 Android 数据予以保留。

首装对发行包及初始公钥的信任由用户确认；安装后的更新只由已安装、root 拥有的后端验证，不能用更新包替换验证公钥或执行尚未认证的下载代码。图形确认与最终执行绑定同一份签名清单，在线更新还校验签名版本与 GitHub 宣告版本一致，拒绝伪装为更新的旧版本回放。

## 命令行

以下示例在已安装工具后运行。只读状态无需提权；完整私有状态及修改操作使用 `pkexec`。输出为 JSON，不包含备份内容、密码或校准数据。

```bash
python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py status
python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py check-updates
python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py catalog --channel stable
python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py download \
  --output ~/Downloads/OXP3 --select input hdr
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py plan \
  --bundle /path/to/selection-ID.tar.gz --select input hdr --selected-only
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py update \
  --bundle /path/to/selection-ID.tar.gz --select input hdr --selected-only
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py apply \
  --bundle /path/to/selection-ID.tar.gz --select input hdr --selected-only
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py apply \
  --bundle /path/to/oxp3-maintenance-VERSION-linux-x86_64.tar.gz --tool-only
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py rollback
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py restore --select gyro
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py recover
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py logs
```

`download --select` 以普通用户运行，自动包含依赖，返回 JSON 的 `path` 是生成的选择包路径；将示例的 `/path/to/selection-ID.tar.gz` 替换为该值，再提权预检或安装。省略 `--select` 只下载核心入口；`download --all-components` 可提前组成包含全部可交付组件的离线包。Opti 插件使用 `--select opti2xmx`；只有明确选择 `opti2xmx-runtime` 才加入可选大体积 XMX 运行库。root 后端不联网，缺少所选组件或依赖时拒绝安装。

`apply` 允许同版本添加选项；`update` 要求项目版本增加，普通操作均拒绝降级。`--selected-only` 只刷新明确选择及依赖；不加此参数时，兼容且可接管的原选择会自动参与更新。`--tool-only` 绕过组件目录解析，仅更新已验签的维护程序，可用于未来适配器升级。`plan --all-components` 预检全部选项，不执行写入。自动检查是普通用户的 systemd timer；图形安装（含仅安装工具）会启用它。纯命令行安装后可运行：

```bash
systemctl --user daemon-reload
systemctl --user enable --now oxp3-maintenance-check.timer
```

## 恢复行为

状态和安装前原件保存在 root 私有的 `/home/.oxp3-maintenance`。每次修改共用一个锁；事务先持久记录意图，再写入目标。更新代码使用独立版本目录，旧工具保持可恢复，入口最后切换。

维护代码目录同时包含项目版本和内容摘要；同版本增加选项、重新构建维护工具也不会原地覆盖正在运行的恢复代码。旧版组件选择、已接管的历史和当前文件所有权分别记录，首次只装维护工具不会丢掉旧选择；恢复组件后也不会从旧安装器记录中自动重新安装。

- **回退上次项目更新**：恢复上一代文件与对应服务状态。
- **恢复组件原状**：恢复该组件受管文件的安装前原件；被用户修改的可变配置保留。依赖组件需要先一起恢复。
- **恢复中断的操作**：只处理记录所属的当前槽，检查每个目标是否仍等于写前或写后状态，再完成恢复。存在外部改动时保留现场，显示需要处理的路径。
- 服务初始状态和每代状态独立持久记录；失败时恢复根文件系统保护，未恢复一致前不启动受影响服务。旧安装器没有保存的历史服务策略无法凭空还原，首次维护时的状态作为服务基线。
- Waydroid 宿主包只安装本项目固定的五个包，拒绝替换不同的已有版本。恢复只移除由工具新增且仍为该版本的包，不删除 Android 数据。包解包中断但尚未登记数据库时，尝试用持久保存的同一归档完成登记再移除；失败则保留待处理记录。恢复后如需再次安装 Waydroid，应重新选择安装，不能通过回退绕过包安装检查。

维护工具自身会保留为恢复入口。事务和临时副本需要额外空闲空间，开始修改前会检查共享 home 和目标文件系统容量。当前实现保存原件及上一代事务，运行库保留用于回退的代码；不要手动删除私有状态目录。

## 构建与验证

推荐使用模块打包模式，生成小型核心入口、完整签名目录、独立组件附件、轻量安装脚本、公钥及校验清单，无需构建 Windows 安装器。1.0.6 的版本声明与独立 Opti 插件准备步骤见 [1.0.6 发布准备](docs/RELEASE-1.0.6.md)：

```bash
python3 package_release.py --modular --payload /path/to/prepared-1.0.6 \
  --public-key /secure/publisher-public.pem \
  --private-key /secure/publisher-private.pem \
  --output-dir /releases/maintenance-1.0.6 \
  --tag maintenance-v1.0.6 --opti-tag maintenance-assets-v1.0.6
```

输出目录须尚不存在且位于源码、载荷目录之外；父目录须已存在。流程不改源码目录的公钥，不生成生产密钥，失败不保留半成品发行目录，也不上传或发布。`maintenance/` 面向本项目维护 Tag，`opti2xmx/` 面向独立 Opti2XMX 仓库，`release-plan.json` 列出新附件与复用地址。传入 `--previous-catalog`、`--previous-signature` 可沿用已签发目录中内容完全相同的旧附件。完整流程见 [独立打包说明](docs/PACKAGING.md) 和 [模块分发协议](docs/modular-distribution.md)。省略 `--modular` 保留传统完整离线包模式；下面的 `build_bundle.py` 是底层单包入口。

发布包必须使用安装器已经准备好的规范载荷目录：`components/`、`integration/`、`plugins/`、`waydroid/`、`hdr/`、`controls/`、`licenses/`。准备时将本仓库的 `LICENSE` 和所分发第三方组件的许可及对应源码说明一并放入 `licenses/`。大体积运行库、第三方固件和插件不是 Git 源码的一部分；构建器不会自动采集研究目录、设备快照、Windows 运行库或凭据。

先用 `python3 prepare_payload.py --workspace /path/to/current-workspace --output /path/to/prepared-payload` 从明确指定的当前安装器源码和已准备缓存生成载荷。工具不执行载荷代码、不下载依赖；检查当前选项、缓存版本、资源来源、路径和第三方材料，保留 `components/preparation-report.json` 的逐项覆盖及来源记录。资源不完整时不应签发。

项目版本唯一来源为准备载荷的 `components/release.json`。发布者先在发行环境配置真实 Ed25519 私钥，将对应公钥保存到源码目录的 `trusted-public-key.pem` 并公布；私钥必须位于输入目录之外，不进入 Git 或发行包。工具不会生成虚假的生产密钥。

```bash
cd steamos-maintenance
python3 build_bundle.py --payload /path/to/prepared-payload \
  --private-key /private/oxp3-release-private.pem \
  --output /releases/oxp3-maintenance-VERSION-linux-x86_64.tar.gz
python3 -m unittest discover -s tests -v
```

构建器固定文件顺序和归档时间，签名原始清单并记录 SHA-256，再自验归档。验证拒绝未声明文件、特殊文件、软硬链接、越界路径、重复条目、未完整携带的组件组和超限归档。在线源限定为本项目与 Opti2XMX 的 GitHub Release 附件，包含 Beta 发布；离线选择包执行相同校验。

模块构建生成的 `oxp3-maintenance-VERSION-catalog.json` 及 `.sig` 是完整目录，包括全部组件、依赖、交付方式、核心摘要及各独立附件的固定地址、大小和摘要。核心与目录放在本次维护 Tag；不变组件可继续引用旧维护 Tag 或独立 Opti2XMX Tag 的附件。发布时应先确保全部引用可用，再开放新目录，并保留仍被引用的旧附件。传统单包模式的目录仍绑定对应完整包。本分支没有上传或发布；内部验收使用一次性 QA 密钥，不构成正式发行信任配置。

验证记录见 [VALIDATION.md](VALIDATION.md)。完成签名发行配置及 OXP3 实机的桌面操作、首次应用、跨版本更新、重启和休眠验收后，再提供面向普通用户的下载包。

源代码遵循项目许可证。第三方组件保留原有许可证和对应源码义务；维护包必须保留准备载荷中的第三方许可材料。
