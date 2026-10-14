# XMX runtime / XMX 运行环境

Version 0.2.1 manages an already staged runtime. It does not download or install the XMX driver/compiler stack. / 0.2.1 只管理已经准备好的运行环境，不自动下载或安装 XMX 驱动和编译器。

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
