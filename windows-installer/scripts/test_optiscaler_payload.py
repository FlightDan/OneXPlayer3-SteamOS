"""Offline archives must be complete and pinned before integration is regenerated."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import runpy
import sys
from types import SimpleNamespace
import subprocess

import optiscaler_payload as payload


class OptiScalerPayloadTests(unittest.TestCase):
    def test_release_pins_match_the_shipped_plugin_cache_keys(self):
        plugin = Path(__file__).resolve().parents[1] / 'components/opti2xmx'
        sys.path.insert(0, str(plugin))
        try:
            releases = runpy.run_path(str(plugin / 'opti.py'))['RELEASES']
        finally:
            sys.path.remove(str(plugin))
        actual = json.loads((plugin.parent / 'optiscaler-release.json').read_text(encoding='utf-8'))
        self.assertEqual({item['version'] for item in actual['archives']}, set(releases))
        for pin in actual['archives']:
            self.assertEqual((pin['tag'], pin['filename']), releases[pin['version']][:2])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archives = []
        self.pins = {'schema': 1, 'archives': []}
        for actual in payload.PINS['archives']:
            version = actual['version']
            archive = self.root / actual['filename']
            archive.write_bytes(b'7z\xbc\xaf\x27\x1c' + version.encode())
            self.archives.append(archive)
            self.pins['archives'].append({
                **actual,
                'size_bytes': archive.stat().st_size,
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            })
        patch = mock.patch.object(payload, 'PINS', self.pins)
        patch.start()
        self.addCleanup(patch.stop)

    def test_all_pinned_original_archives_are_staged_in_the_plugin_cache_layout(self):
        output = self.root / 'prepared'
        report = payload.prepare(self.archives, output)
        files = payload.read_cache(output)
        self.assertFalse(report['contains_game_state'])
        self.assertEqual(report, dict(self.pins, contains_game_state=False))
        self.assertEqual(len(files), len(self.pins['archives']))
        for pin, archive in zip(self.pins['archives'], self.archives):
            target = payload.CACHE_TARGET + pin['tag'] + '/' + pin['filename']
            self.assertEqual(files[target], archive.read_bytes())
        self.assertEqual(sorted(p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()),
                         sorted(['manifest.json'] + [p['tag'] + '/' + p['filename'] for p in self.pins['archives']]))
        with self.assertRaisesRegex(ValueError, 'fresh'):
            payload.prepare(self.archives, output)

    def test_prepared_archives_are_found_by_the_real_plugin_without_network(self):
        plugin = Path(__file__).resolve().parents[1] / 'components/opti2xmx'
        sys.path.insert(0, str(plugin))
        try:
            from manager import Manager
            import opti
            import fsr
        finally:
            sys.path.remove(str(plugin))
        prepared = self.root / 'prepared'
        payload.prepare(self.archives, prepared)
        home = self.root / 'home'
        for target, data in payload.read_cache(prepared).items():
            path = home / target.removeprefix('/home/deck/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manager = Manager(home, engine=SimpleNamespace(no_symlink_parents=lambda path: None))

        def extract(args, **kwargs):
            self.assertEqual(args[:3], ['7z', 'e', '-so'])
            self.assertTrue(Path(args[3]).is_file())
            return subprocess.CompletedProcess(args, 0, b'MZ fixture' if args[-1].endswith('.dll') else b'[fixture]\n')

        with mock.patch.object(opti.urllib.request, 'urlopen', side_effect=AssertionError('Network attempted')), \
                mock.patch.object(fsr, 'descriptor') as descriptor:
            for pin in self.pins['archives']:
                # Nightly package verification uses the same fixture's real
                # size/hash; production archive pins are never changed here.
                descriptor.return_value = {'opti_archive': pin}
                with mock.patch.object(opti.subprocess, 'run', side_effect=extract) as commands:
                    extracted = manager.opti_package(pin['version'], 'github')
                    self.assertTrue(commands.called)
                    self.assertTrue((extracted / 'OptiScaler.dll').is_file())
                with mock.patch.object(opti.subprocess, 'run', side_effect=AssertionError('Re-extraction attempted')):
                    self.assertEqual(manager.opti_package(pin['version'], 'github'), extracted)

    def test_missing_or_duplicate_version_cannot_create_a_partial_cache(self):
        for archives in (self.archives[:1], [self.archives[0], self.archives[0]]):
            output = self.root / 'incomplete'
            with self.assertRaisesRegex(ValueError, 'exactly'):
                payload.prepare(archives, output)
            self.assertFalse(output.exists())

    def test_changed_archive_is_rejected_before_any_output(self):
        self.archives[-1].write_bytes(b'not the official archive')
        output = self.root / 'invalid'
        with self.assertRaisesRegex(ValueError, 'pinned release'):
            payload.prepare(self.archives, output)
        self.assertFalse(output.exists())

    def test_changed_cache_and_rewritten_local_provenance_are_rejected(self):
        output = self.root / 'prepared'
        payload.prepare(self.archives, output)
        pin = self.pins['archives'][0]
        (output / pin['tag'] / pin['filename']).write_bytes(b'corrupt cache')
        with self.assertRaisesRegex(ValueError, 'pinned release'):
            payload.read_cache(output)
        report = json.loads((output / 'manifest.json').read_text())
        report['archives'][0]['sha256'] = '0' * 64
        (output / 'manifest.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'provenance'):
            payload.read_cache(output)


if __name__ == '__main__':
    unittest.main()
