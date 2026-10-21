"""Build provenance regressions using temporary public-source fixtures."""
import importlib.util
import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('hdr_source_inputs', Path(__file__).with_name('prepare-source-inputs.py'))
inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inputs)


class SourceInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'ci'
        self.destination.mkdir()
        for name in inputs.INPUTS:
            source = self.root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b'public fixture\r\n')
        pin = patch.object(inputs, 'PINNED_ARCHIVE_INPUTS', {
            'research/display-source/kwin-6.7.3-1.6.src.tar.gz':
                (len(b'public fixture\r\n'), hashlib.sha256(b'public fixture\r\n').hexdigest()),
        })
        pin.start()
        self.addCleanup(pin.stop)

    def test_allowlist_excludes_unrelated_local_research_and_metadata(self):
        (self.root / 'research' / 'unrelated-local-study.txt').write_text('must stay local', encoding='utf8')
        inputs.prepare(self.root, self.destination, write=True)
        with tarfile.open(self.destination / 'source-inputs.tar') as archive:
            self.assertEqual(archive.getnames(), list(inputs.INPUTS))

    def test_rebuild_is_deterministic_across_lf_and_crlf_checkouts(self):
        inputs.prepare(self.root, self.destination, write=True)
        original = (self.destination / 'source-inputs.tar').read_bytes()
        for name in inputs.INPUTS:
            if not name.endswith('.tar.gz'):
                (self.root / name).write_bytes(b'public fixture\n')
        inputs.prepare(self.root, self.destination, write=False)
        inputs.prepare(self.root, self.destination, write=True)
        self.assertEqual((self.destination / 'source-inputs.tar').read_bytes(), original)

    def test_changed_renderer_cannot_build_using_old_ci_inputs(self):
        inputs.prepare(self.root, self.destination, write=True)
        (self.root / 'research/desktop-hdr/pattern-wayland.cpp').write_text('new renderer', encoding='utf8')
        with self.assertRaisesRegex(RuntimeError, 'Stale source-manifest'):
            inputs.prepare(self.root, self.destination)

    def test_matching_manifest_cannot_hide_stale_archive(self):
        inputs.prepare(self.root, self.destination, write=True)
        archive = self.destination / 'source-inputs.tar'
        original = archive.read_bytes()
        (self.root / 'research/desktop-hdr/pattern-wayland.cpp').write_text('new renderer', encoding='utf8')
        inputs.prepare(self.root, self.destination, write=True)
        archive.write_bytes(original)
        with self.assertRaisesRegex(RuntimeError, 'Stale CI source archive member'):
            inputs.prepare(self.root, self.destination)

    def test_added_archive_member_is_rejected(self):
        inputs.prepare(self.root, self.destination, write=True)
        with tarfile.open(self.destination / 'source-inputs.tar', 'a') as archive:
            archive.addfile(tarfile.TarInfo('unapproved.txt'))
        with self.assertRaisesRegex(RuntimeError, 'explicit input allowlist'):
            inputs.prepare(self.root, self.destination)

    def test_public_checkout_can_reuse_only_pinned_upstream_blob(self):
        inputs.prepare(self.root, self.destination, write=True)
        (self.root / 'research/display-source/kwin-6.7.3-1.6.src.tar.gz').unlink()
        inputs.prepare(self.root, self.destination, write=True)
        inputs.prepare(self.root, self.destination)
        (self.root / 'research/desktop-hdr/pattern-wayland.cpp').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Missing or linked source input'):
            inputs.prepare(self.root, self.destination)

    def test_upstream_archive_cannot_silently_change(self):
        (self.root / 'research/display-source/kwin-6.7.3-1.6.src.tar.gz').write_bytes(b'changed upstream')
        with self.assertRaisesRegex(RuntimeError, 'Pinned upstream archive hash mismatch'):
            inputs.prepare(self.root, self.destination, write=True)


if __name__ == '__main__':
    unittest.main()
