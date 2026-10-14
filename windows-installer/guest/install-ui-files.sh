#!/bin/sh
set -eu
for file in installer_ui.py ui_model.py ui_backend.py install_session.py intent_store.py deployment.py fs_metadata.py media_layer.py resources.py layout.py handoff.py component_choice.py bootstrap_payload.py; do
    cp "/mnt/payload/tasks/$file" "/mnt/root/usr/local/lib/oxp3-installer/$file"
    chmod 0644 "/mnt/root/usr/local/lib/oxp3-installer/$file"
done

sh /mnt/payload/tasks/install-firstboot-library.sh
