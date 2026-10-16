# XMX runtime / XMX 运行环境

Opti2XMX 0.2.3 provides an explicit **Download and configure XMX runtime** button. The small plugin ZIP contains no runtime binaries; OptiScaler installation and management work without them. A full XMX runtime is a separate 195,558,423-byte (195.6 MB / 186.5 MiB) download. / 0.2.3 提供独立的“下载并配置 XMX 运行环境”按钮，小体积插件 ZIP 不含运行库；没有这些组件仍能安装和管理 OptiScaler。完整 XMX 组件单独下载，大小 195,558,423 字节（195.6 MB / 186.5 MiB）。

**Release state:** the bundled `runtime-source.json` pins the verified composite archive SHA-256, size and exact [v0.2.3 release asset](https://github.com/FlightDan/Opti2XMX/releases/download/v0.2.3/opti2xmx-xmx-runtime-20261005-aa384e5704286e2d.tar.gz). The download starts only when requested. Do not substitute an upstream-only archive: this composite contains the patched Mesa ANV, `igdext64.dll`, IGC/ocloc, compiler helpers, SDK `libxess.dll` and their license files. It contains no OptiScaler. / **发布状态：** `runtime-source.json` 固定已核验完整压缩包的 SHA-256、大小和 v0.2.3 的精确附件地址，仅点击按钮后下载。不能替换成上游原始压缩包：完整组件含修改版 Mesa ANV、`igdext64.dll`、IGC/ocloc、编译辅助程序、SDK `libxess.dll` 和许可文件，不含 OptiScaler。

The button requires x86_64 Linux, an Intel GPU, and host `bash`, `python3`, `ldd`, `vulkaninfo`. It downloads only on click, verifies the pinned size and SHA-256, rejects traversal, symlinks, hardlinks, special files and oversized archives, then validates the driver and compiler on the host. Only after those checks does it atomically update the user's `runtime.json`. Download progress and final errors remain visible; a failed operation can be retried. An unpublished asset is not reported as success. / 按钮需要 x86_64 Linux、Intel GPU 和上述系统命令。仅点击后下载，校验固定大小和 SHA-256，拒绝路径越界、软／硬链接、特殊文件和超限压缩包，然后检查驱动和编译器依赖。所有检查通过才原子更新用户的 `runtime.json`。下载进度与错误持续显示，失败后可重试，不会把尚未发布的资源报告为成功。

Downloaded runtimes live under `~/.local/share/opti2xmx/runtimes/<version>-<hash>-<unique>/`, with `runtime/` and `sdk/` subdirectories. Existing runtime directories are retained because per-game launchers may reference them. No system driver is replaced, no root command is run, and no game or OptiScaler files are changed by runtime setup. Existing configuration remains unchanged on download, integrity, extraction or host-validation failures. / 下载的运行环境保存在用户目录的独立版本路径内，已有目录会保留，因为游戏启动器可能仍引用它们。不替换系统驱动，不执行 root 命令，不修改游戏或 OptiScaler 文件。下载、校验、解压或主机检查失败时保留原配置。

The 0.2.3 runtime package supplements the validated development archive with upstream copyright/license notices and source/build references. Its driver, DLL, compiler and helper bytes are unchanged. The same release also carries the corresponding xess-xmx-linux and Mesa source archives; the runtime's existing patches describe the ANV changes. / 0.2.3 的运行库包为已验证的开发压缩包补齐上游版权、许可和来源／构建说明，驱动、DLL、编译器及辅助脚本逐字节不变。同一 Release 另附对应的 xess-xmx-linux 与 Mesa 源码包，运行库中已有补丁记录 ANV 修改。

## Release preparation / 发布准备

The plugin's bundled descriptor is its trust root; it never downloads a replacement descriptor from the network. To enable a future release, publish the reviewed composite raw archive as an immutable asset in `FlightDan/Opti2XMX`, then update `runtime-source.json` in a reviewed plugin build with `published: true`, its exact HTTPS release-asset URL, size and SHA-256. The released asset name is `opti2xmx-xmx-runtime-20261005-aa384e5704286e2d.tar.gz`; SHA-256 is `aa384e5704286e2d765ed9770e6599ad8e46e2d15821c1f9e51682f3521aa50b`. Do not use `latest`, mutable remote metadata, mirror URLs, or the maintenance installer's outer shard as the raw archive. / 插件内置描述是可信来源，不从网络下载替代描述。未来发布经过审核的完整原始压缩包后，在经过审核的插件构建中填写 `published: true`、精确 HTTPS Release 资源地址、大小和 SHA-256。不得使用 `latest`、可变远程元数据、镜像或维护器外层分片代替原始压缩包。

The maintenance distribution may additionally sign its own descriptor/catalog; the standalone plugin relies on its bundled hash pin and does not fetch or trust those external descriptors. Its optional runtime shard wraps the raw archive at `payload/integration/opti2xmx/runtime.tar.gz`. A maintenance plugin-only installation must omit `runtime.json`; the separate runtime component may configure `/opt/oxp3-opti2xmx/20261005/{runtime,sdk}`. A later successful standalone button action replaces the user's pointer with its own validated user-data paths. / 维护发行包可另外签名描述和目录；独立插件依靠内置哈希，不获取或信任外部描述。维护器的运行环境分片在上述位置封装原始压缩包。仅安装插件时应省略 `runtime.json`，独立运行环境组件可配置 `/opt` 路径。以后按钮安装成功会将用户配置指向它验证过的用户目录。

## Already prepared runtimes / 已准备的运行环境

Default layout / 默认目录：

```text
~/.local/share/opti2xmx/
  sdk/libxess.dll
  runtime/
    igdext64.dll
    lib/libvulkan_intel.so
    tools/cm-compile.sh
    tools/cmk_pack.py
    igc/neo/bin/ocloc
    igc/neo/lib/x86_64-linux-gnu/...
    igc/igc/local/lib/libigc.so...
    igc/igc/local/lib/libigdfcl.so...
```

The SR library must report version 2.0.2.68 or later. Compiler helpers and ocloc must be executable. All driver/compiler dependencies must resolve on the target system. / SR 库版本需为 2.0.2.68 或更高；编译辅助脚本和 ocloc 必须可执行，依赖库必须能在目标系统解析。

Alternatively, create `~/.local/share/opti2xmx/runtime.json` with absolute paths owned by your Steam user / 或写入当前 Steam 用户拥有的绝对路径：

```json
{
  "package": "/home/YOUR_USER/.local/share/opti2xmx/runtime",
  "sr": "/home/YOUR_USER/.local/share/opti2xmx/sdk/libxess.dll"
}
```

Replace `YOUR_USER`. Do not run the plugin as root. / 替换 `YOUR_USER`，不要以 root 运行插件。

The development baseline used [xess-xmx-linux release 20261005](https://github.com/HHHHanasak1/xess-xmx-linux/releases/tag/20261005), IGC 2.10.10, ocloc 25.18.33578.6, and the SR library from [Intel XeSS v3.0.2](https://github.com/intel/xess/tree/v3.0.2). These version references are provenance, not a tested universal installer recipe. Follow upstream build and license instructions; an upstream archive may not contain the complete layout above.

开发基线使用上述版本，但这些记录不是通用安装方案。请遵循上游构建及许可说明；上游压缩包不一定包含完整目录。插件会检查驱动加载、Vulkan 枚举和编译器可用性；这些检查不能证明实际游戏已执行 XMX。

For compatibility with existing 0.2.1 development installations, the backend also recognizes legacy `~/oxp3-research/xess/` and `~/oxp3-research/xess-sr/` locations. New installations should use the standard paths above. / 为兼容已有开发安装，后端保留旧目录回退；新安装请使用标准目录。
