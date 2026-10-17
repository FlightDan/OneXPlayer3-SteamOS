# Third-party notices / 第三方说明

The AGPL-3.0-only license applies to original Opti2XMX code, not to separately downloaded components. / AGPL-3.0-only 许可证适用于本项目原创代码，不覆盖另行下载的组件。

- **Decky**: [plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template), [API](https://github.com/SteamDeckHomebrew/decky-frontend-lib). The template's BSD 3-Clause notice is retained in LICENSE. JavaScript dependency versions are pinned in pnpm-lock.yaml; their own licenses continue to apply.
- **OptiScaler**: [source and licenses](https://github.com/optiscaler/OptiScaler). Downloaded on explicit user request from pinned official releases, or a user-selected mirror. No OptiScaler binaries are committed or bundled. The installer preserves allowlisted license files from the downloaded archive.
- **xess-xmx-linux**: [source, documentation and releases](https://github.com/HHHHanasak1/xess-xmx-linux). The plugin ZIP contains no runtime binaries. The separate XMX runtime asset preserves upstream notices, patches and source/build references; see [runtime setup](docs/RUNTIME.md).
- **Intel XeSS**: [SDK and license](https://github.com/intel/xess). The separate XMX runtime asset includes SDK `libxess.dll` and its Intel license. Intel's terms apply to the DLL, independently of this project's AGPL-3.0-only license.
- **Mesa ANV, Intel IGC and compute-runtime/ocloc**: included only in the separate runtime asset, with their own licenses, notices and source/build references. Generated kernels, game files and private binary caches are not distributed.

Do not infer permission to redistribute a complete third-party runtime bundle from this repository's license. / 不要将本仓库的许可证视为重新分发整套第三方运行环境的许可。
