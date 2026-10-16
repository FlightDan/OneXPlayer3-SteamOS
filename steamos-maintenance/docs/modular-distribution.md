# Modular maintenance distribution

`build_distribution.py` is the primary build command for an on-demand release.
It uses a complete prepared Linux payload and a source tree containing the pinned
publisher `trusted-public-key.pem`. Keep the private key outside both inputs.
The build does not upload, publish, tag, push, or merge anything.

The public-key staging wrapper supports the same workflow with an explicit key,
without changing a checkout's existing trust-key file:

```sh
python3 package_release.py --modular \
  --payload /build/prepared-0.1.4 --source /build/maintenance-source \
  --public-key /secure/publisher-public.pem \
  --private-key /secure/publisher-private.pem --output-dir /build/release-0.1.4 \
  --tag maintenance-v0.1.4 --opti-tag maintenance-assets-v0.1.4
```

`--previous-catalog` and `--previous-signature` enable exact asset reuse in this
wrapper too. Outputs use the same `maintenance/`, `opti2xmx/`, and release-plan
layout. Without `--modular`, `package_release.py` retains the complete legacy
offline packaging mode.

```sh
python3 build_distribution.py \
  --payload /build/prepared-payload \
  --source /build/maintenance-source \
  --private-key /secure/publisher-private.pem \
  --output-dir /build/release-1.2.3 \
  --tag maintenance-v1.2.3 \
  --opti-tag maintenance-assets-v1.2.3
```

The resulting `maintenance/` directory contains the stable core archive filename,
signed complete capability catalog, bootstrap installer, publisher public key,
new maintenance component archives, and checksums. `opti2xmx/` contains new Opti
plugin/runtime assets for `FlightDan/Opti2XMX`. `release-plan.json` lists the exact
repositories, immutable tags, asset URLs, and new or reused package identifiers.
All eight retired third-party Decky plugins are removed from a fresh payload
staging copy, including legacy metadata and concealed integration file entries.

The prepared Opti runtime is preserved byte for byte. It is a composite XMX
runtime, not an OptiScaler download or an arbitrary upstream substitution. Its
plugin notices remain with the Opti plugin group; general runtime inventory and
notices remain available in the mandatory core.
The small `opti2xmx` plugin depends only on Decky. The separate
`opti2xmx-runtime` component is optional, defaults off, and depends on the plugin;
only selecting this runtime downloads the large XMX archive. Old prepared
payloads are split in staging, including moving their fixed runtime configuration
out of the plugin component. The input payload is left unchanged.

The Opti staging directory also contains a standalone raw composite runtime asset
and signed `runtime-source.json`/`runtime-source.sig`. Its proposed immutable URL,
compressed size, and SHA256 are recorded in the signed distribution. Local
staging metadata deliberately says `published: false` and `url: null`. The
standalone plugin's download button must remain unavailable until its bundled
descriptor is explicitly updated for a published, checksum-pinned asset. The
plugin archive itself contains no XMX runtime binaries.

A new release can reuse unchanged assets from any earlier release:

```sh
python3 build_distribution.py \
  --payload /build/prepared-payload --source /build/maintenance-source \
  --private-key /secure/publisher-private.pem --output-dir /build/release-1.2.4 \
  --previous-catalog /archive/1.2.3/oxp3-maintenance-1.2.3-catalog.json \
  --previous-signature /archive/1.2.3/oxp3-maintenance-1.2.3-catalog.sig
```

The previous catalog must verify with the pinned key. Reuse requires exact file
membership, hashes, sizes, modes, deterministic archive name, compressed size,
and compressed archive hash. References retain their earlier immutable release
URL. Reused assets are absent from the new staging directories and stay listed
in the complete new catalog. A client therefore needs only the latest catalog,
even when upgrading directly from a much older version. Never delete old assets
while a supported catalog references them.

## Signature and compatibility layout

The catalog uses schema 2. `bundle` points to a schema-1 **core seed** retaining
`oxp3-maintenance-VERSION-linux-x86_64.tar.gz`. This archive contains the tool,
complete selection metadata, small common repair resources, and two signed data
files:

- `payload/components/distribution-manifest.json`
- `payload/components/distribution-manifest.sig`

The inner schema-2 manifest authenticates all files, disjoint atomic package
membership, component-to-package mappings, component revisions and dependencies,
and immutable non-core asset references. The outer schema-1 signature binds the
inner signed bytes and the exact core files. Older installed backends can verify
and apply this core archive for a tool-only bridge upgrade. They must not attempt
a component installation from the sparse core seed.

Current clients use `distribution.describe_source(source, key)` for a trusted
catalog-shaped view without requiring a separately downloaded catalog. They call
`distribution.materialize(source, selected, destination, key, catalog=None,
cache=None, opener=None, progress=None)` as the unprivileged user. `destination`
is a new output archive path, and `selected` contains component IDs. The method
returns `path`, `manifest`, `packages`, `components`, and `downloaded`. If supplied,
the signed catalog must agree with the source's complete embedded distribution.

Materialization expands the full dependency closure, downloads only missing
atomic groups, verifies cached or downloaded compressed hashes and exact file
records, and creates a schema-2 sparse archive. Existing groups in an imported
sparse archive are retained. An empty selection creates a core-only schema-2
archive suitable for a tool-only operation. Network targets are bounded HTTPS
GitHub release asset URLs in the two publisher repositories, with restricted
GitHub asset redirect hosts. Unavailable components, missing references, cycles,
partial groups, unsafe paths, unsigned files, corrupt caches, oversized streams,
and changed bytes fail closed.

The privileged backend performs no network access. It verifies the assembled
archive again with its installed pinned key, checks that every selected component
and dependency has all required groups, and runs the existing live preflight.
A tool-only upgrade must never record repair/plugin revision receipts. Successful
component operations record revisions only for the selected components and slot.
Component revisions include their installation adapter code and, for gyro, the
installed gyro binding helper. An adapter change can require a repair refresh
while keeping the exact unchanged runtime archive reference. UI-only code changes
do not invalidate component receipts.

`bundle.inspect_bundle` and `verify_bundle` preserve schema-1 results unchanged.
For schema 2, `files` is the authenticated present subset, `signed_files` is the
complete authenticated file map, and `present_packages` identifies complete
present groups. `bundle.manifest_digest` returns the canonical full signed
manifest digest for catalog binding; a review digest should also include the
present subset/package selection. `distribution.index_from_manifest` exposes the
trusted index from an authenticated manifest view. Raw signatures remain in the
assembled archive so copying the archive offline preserves root reverification.

The complete legacy offline packaging mode remains available without
`--modular`; cross-release asset reuse requires modular mode.
