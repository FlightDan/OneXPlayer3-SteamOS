The bundled `flathub.flatpakrepo` was downloaded on 2026-10-14 from
https://dl.flathub.org/repo/flathub.flatpakrepo. It contains Flathub's public
signing key and repository metadata, not a private key.

The installer changes only the repository URL to the USTC mirror and stages
the complete definition in `/etc/flatpak/remotes.d/flathub.flatpakrepo`.
Flatpak creates the repository and imports the signing key when it first
uses the preconfigured system remote. Existing Flathub repo configuration
also receives the mirror URL, preserving its other settings and key files.
All staged files use the component's existing snapshot/restore mechanism.

References:
- https://docs.flatpak.org/en/latest/flatpak-command-reference.html
- https://mirrors.ustc.edu.cn/help/flathub.html
