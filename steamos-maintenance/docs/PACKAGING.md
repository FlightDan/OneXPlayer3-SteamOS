# 独立维护工具发行打包

推荐使用 `package_release.py --modular`：常用小修复与维护程序放在核心包，大型驱动/运行库和本项目插件独立分发，用户按选择下载。此流程只在本机生成发行文件，不提交、不上传，也不创建 GitHub Release；无需构建 Windows 安装器。

0.1.4 的明确版本声明、独立 Opti 插件 ZIP 与输入准备步骤见 [0.1.4 发布准备](RELEASE-0.1.4.md)。签名布局、接口及跨 Release 复用规则见 [模块分发协议](modular-distribution.md)。

## 发布者准备

需要 Python 3.10 或更新版本、支持 Ed25519 的 OpenSSL，以及完整准备好的 Linux 载荷，包含 `components/release.json`、`components/options.json` 和 `integration/manifest.json`。版本和能力信息来自这些明确输入，不由打包器补造；组件安装仍执行原有的验签、兼容性检查和实时预检。

发布者提供正式 Ed25519 私钥及匹配公钥。私钥放在源码和载荷目录之外，不进入 Git 或发行包。输出目录同样位于输入目录之外，必须尚不存在，其父目录须已存在。打包流程不生成生产密钥。

```bash
python3 package_release.py --modular \
  --source /work/steamos-maintenance \
  --payload /work/prepared-0.1.4 \
  --public-key /secure/publisher-public.pem \
  --private-key /secure/publisher-private.pem \
  --output-dir /work/releases/maintenance-0.1.4 \
  --tag maintenance-v0.1.4 \
  --opti-tag maintenance-assets-v0.1.4
```

`--source` 默认是脚本目录；`--openssl` 可指定 OpenSSL 可执行文件。流程将允许的维护 Python 源码、启动器、可选 README/VALIDATION 文档与规范化公钥复制到私有暂存目录，再调用模块构建器。显式公钥仅用于暂存副本，不修改源码中已有的 `trusted-public-key.pem`。旧准备载荷也会在暂存副本中移除已停止分发的第三方 Decky 插件，并将可选 XMX 运行库与 Opti 插件分开；原输入保持不变。

构建完成后自验签名、核心与组件归档，再生成轻量安装脚本和校验清单；全部成功才将暂存产物目录重命名为最终输出目录。失败清理暂存目录，不留下貌似完整的发行目录；既有输出不会被覆盖。

## 模块产物

以 0.1.4 为例：

| 路径 | 用途 |
| --- | --- |
| `maintenance/oxp3-maintenance-0.1.4-linux-x86_64.tar.gz` | 小型维护程序、常用修复、完整选择元数据及签名分组清单；兼容旧后端的仅工具升级 |
| `maintenance/oxp3-maintenance-0.1.4-catalog.json` 与 `.sig` | 完整能力目录及 Ed25519 签名，列出所有组件、依赖和固定附件引用 |
| `maintenance/oxp3-package-*.tar.gz` | 本次新增或变化的大型驱动/运行库、本项目独立插件组 |
| `maintenance/install-oxp3-maintenance.sh` | 内嵌本地引导代码和固定公钥的轻量安装脚本 |
| `maintenance/trusted-public-key.pem` | 规范化发行公钥 |
| `opti2xmx/oxp3-package-*.tar.gz` | 本次新增或变化的轻量 Opti 插件组及独立可选 XMX 运行库组 |
| `opti2xmx/opti2xmx-xmx-runtime-*.tar.gz` | 供独立插件使用的原始组合 XMX 运行库附件，内容与清单中的内层运行库一致 |
| `opti2xmx/runtime-source.json` 与 `.sig` | 本地运行库附件描述及签名；准备期标为未发布，不能当作已可下载地址 |
| `maintenance/SHA256SUMS`、`opti2xmx/SHA256SUMS` | 各目录当前生成文件的 SHA-256 摘要 |
| `release-plan.json` | 目标仓库、Tag、固定地址、新生成包与沿用旧附件的记录 |

常用小修复包含输入、风扇驱动等体积小的资源；Decky、WiFi、陀螺仪、桌面 HDR、管理器、Waydroid 分组下载。本项目风扇、CPU、充电、重启 Windows 插件各自独立。Opti 插件及可选 XMX 运行库附件放到 `FlightDan/Opti2XMX`；其他维护附件放到 `FlightDan/OneXPlayer3-SteamOS`。

选择 `opti2xmx` 只包含轻量插件及 Decky 依赖；`opti2xmx-runtime` 默认关闭，明确选择后才加入大体积 XMX 运行库。第三方现成 Decky 插件由用户自行安装，本流程不重新分发。独立 Opti 插件 ZIP 由其项目单独构建，再作为发布准备输入；不把 XMX 二进制塞进插件 ZIP。

相同输入、参数和密钥重复构建产生相同归档字节；ZIP、tar 和 gzip 的时间与顺序固定。生产私钥、Windows 产物、缓存和字节码不会被隐式复制进发行。

## 完整目录与跨 Release 复用

最新目录始终包含全部可交付组件及其依赖，不是“本次变化列表”。新版本只更新一个插件时，其他组件仍保留在新目录中，并可继续引用它们在旧 Release 的固定附件地址。旧用户获取最新目录即可补齐所需组件，无需按顺序安装中间版本。

已有可信模块目录时，增加以下参数：

```bash
  --previous-catalog /archive/oxp3-maintenance-0.1.3-catalog.json \
  --previous-signature /archive/oxp3-maintenance-0.1.3-catalog.sig
```

旧目录必须通过同一固定公钥验签。只有成员文件、摘要、大小、权限及确定性压缩归档内容完全一致，且仓库来源符合要求，才沿用原附件引用；复用包不会重新出现在本次附件目录。`release-plan.json` 和完整签名目录记录其旧地址。

核心包及目录放在本次 `maintenance-v0.1.4` Tag；Opti 新附件使用独立 Opti2XMX Tag，不变组件可以留在更早的 Tag。正式发布时先确保全部引用附件可下载，再开放最新目录，并保留仍被支持目录引用的旧附件。Windows 安装器 Release 继续保持 Latest；维护 Tag 不标为 Latest。本命令只准备文件，不执行发布。

## 按需下载与离线包

安装后的 CLI 以普通桌面用户查询完整目录并下载所选组件：

```bash
python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py catalog --channel stable
python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py download \
  --output ~/Downloads/OXP3 --select input hdr
```

下载会加入依赖，校验缓存或新取得的分组，组装为可离线复验的选择包。返回 JSON 的 `path` 是该包路径；用它替换下例占位路径：

```bash
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py plan \
  --bundle /path/to/selection-ID.tar.gz --select input hdr --selected-only
pkexec python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py apply \
  --bundle /path/to/selection-ID.tar.gz --select input hdr --selected-only
```

省略下载的 `--select` 只获取核心入口；`download --all-components` 可组成包含全部可交付组件的离线包。root 后端不联网，重新验证签名、完整组件组和实时安装条件；缺少所选组件或依赖就拒绝安装。已有旧维护后端时，先用核心包审核仅工具升级，再安装组件；工具升级不代表旧修复已经更新。

## 可选的传统完整单包

不加 `--modular` 时保留传统完整离线发行模式：

```bash
python3 package_release.py \
  --source /work/steamos-maintenance --payload /work/prepared-linux-payload \
  --public-key /secure/publisher-public.pem \
  --private-key /secure/publisher-private.pem \
  --output-dir /work/releases/full-offline-release
```

此模式直接生成完整 `oxp3-maintenance-VERSION-linux-x86_64.tar.gz`、绑定该完整包的 catalog/signature、安装脚本、公钥和校验清单。它不使用跨 Release 组件引用，`--previous-catalog` 等模块专用参数要求显式开启 `--modular`。

## 引导脚本与验签

`SHA256SUMS` 用于传输核对；信任来自固定的 Ed25519 公钥及签名。首次使用前，从可信项目渠道取得脚本，并通过独立渠道核对项目公布的公钥指纹或已知脚本摘要：

```bash
openssl pkey -pubin -in trusted-public-key.pem -outform DER | sha256sum
sha256sum --check SHA256SUMS
```

也可以单独生成轻量脚本：

```bash
python3 build_installer.py \
  --source /work/steamos-maintenance \
  --public-key /secure/publisher-public.pem \
  --output /work/releases/install-oxp3-maintenance.sh
bash /work/releases/install-oxp3-maintenance.sh --help
```

目标 SteamOS 需要 `/usr/bin/python3`、OpenSSL 和 Bash。脚本使用 `/usr/bin/python3 -I -B`，在私有临时目录内写入固定公钥及可重复 ZIP。白名单包含 `__init__.py`、`bundle.py`、`releases.py`、`catalog.py`、`distribution.py`、`downloads.py`、`bootstrap.py` 七个模块；正常返回和异常都会清理临时目录。它不下载 Python 来执行，也不从网络替换公钥。

脚本支持默认 stable、`--channel beta`、`--version`、`--download-only`、`--output` 及 `--bundle`。默认位置为 `~/Downloads/OXP3`。模块发行中先下载和验证核心，再由原生界面按选择获取分组；实际系统修改需审核并通过系统认证。`--download-only` 本身不下载全部组件，shell 包装层不提权。

## 验证

```bash
python3 -m unittest discover -s tests -p test_packaging.py -v
python3 -m unittest discover -s tests -p test_distribution.py -v
python3 -m unittest discover -s tests -p test_modular_upgrade.py -v
```

测试覆盖模块输出布局、显式公钥、完整目录、跨版本引用复用、依赖闭包、缓存验证、可选 XMX 分离、分组完整性、旧后端升级与传统完整单包兼容，以及失败清理和既有文件保护。Windows 测试使用隔离 Python 执行脚本内嵌程序；SteamOS 上还需实际 Bash 和设备验收。
