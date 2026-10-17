"""Pinned archive staging and provenance validation without executing plugin code."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import opti_payload as payload


class OptiPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime.tar.gz'
        self.runtime.write_bytes(b'public-runtime-fixture')
        self.descriptor = {'schema': 1, 'published': True, 'size_bytes': self.runtime.stat().st_size,
                           'sha256': hashlib.sha256(self.runtime.read_bytes()).hexdigest(), 'url': payload.RUNTIME_URL}
        self.records = {name: b'raise AssertionError("Do not execute plugin data")\n' for name in payload.FILES}
        self.records.update({'plugin.json': b'{"name":"Opti2XMX"}',
                             'package.json': json.dumps({'version': payload.VERSION}).encode(),
                             'runtime-source.json': json.dumps(self.descriptor).encode()})
        self.plugin = self.root / 'plugin.zip'
        self.archive(self.plugin, self.records)
        for name, value in [('RUNTIME_SIZE', self.descriptor['size_bytes']),
                            ('RUNTIME_SHA256', self.descriptor['sha256']),
                            ('PLUGIN_SHA256', hashlib.sha256(self.plugin.read_bytes()).hexdigest()),
                            ('FILES_SHA256', hashlib.sha256(json.dumps({name: hashlib.sha256(data).hexdigest()
                                for name, data in self.records.items()}, sort_keys=True, separators=(',', ':')).encode()).hexdigest())]:
            patch = mock.patch.object(payload, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def archive(self, path, records):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in records.items():
                archive.writestr('opti2xmx/' + name, data)

    def test_exact_members_runtime_and_notices_are_staged_without_input_changes(self):
        output = self.root / 'prepared'
        report = payload.prepare(self.plugin, self.runtime, output)
        self.assertEqual(payload.read_plugin_tree(output / 'plugin'), self.records)
        for name, data in self.records.items():
            self.assertEqual((output / 'integration/sources/opti2xmx' / name).read_bytes(), data)
        self.assertEqual((output / 'integration/opti2xmx/runtime.tar.gz').read_bytes(), self.runtime.read_bytes())
        self.assertEqual(report['runtime'], self.descriptor)
        with self.assertRaisesRegex(ValueError, 'fresh'):
            payload.prepare(self.plugin, self.runtime, output)

    def test_stale_plugin_or_runtime_refuses_output(self):
        self.runtime.write_bytes(b'stale')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            payload.prepare(self.plugin, self.runtime, self.root / 'bad')
        self.assertFalse((self.root / 'bad').exists())
        self.plugin.write_bytes(b'stale archive')
        with self.assertRaisesRegex(ValueError, 'archive differs'):
            payload.read_plugin(self.plugin)

    def test_existing_stale_runtime_is_rejected_by_integration_validator(self):
        cached = self.root / 'cache/opti2xmx/runtime.tar.gz'
        cached.parent.mkdir(parents=True)
        cached.write_bytes(self.runtime.read_bytes())
        payload.validate_runtime(cached)
        cached.write_bytes(b'stale existing archive')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            payload.validate_runtime(cached)

    def test_changed_tree_even_with_rewritten_untrusted_report_is_refused(self):
        output = self.root / 'prepared'
        payload.prepare(self.plugin, self.runtime, output)
        target = output / 'plugin/main.py'
        target.write_bytes(b'modified')
        report = output / 'plugin/deployment.json'
        metadata = json.loads(report.read_text())
        metadata['files']['main.py'] = hashlib.sha256(target.read_bytes()).hexdigest()
        report.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'provenance differs'):
            payload.read_plugin_tree(output / 'plugin')

    def test_unexpected_or_traversal_members_are_rejected(self):
        for name in ('../outside.py', 'dist/extra.js'):
            records = dict(self.records)
            records.pop('main.py')
            records[name] = b'bad'
            self.archive(self.plugin, records)
            with mock.patch.object(payload, 'PLUGIN_SHA256', hashlib.sha256(self.plugin.read_bytes()).hexdigest()):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'member'):
                    payload.read_plugin(self.plugin)


if __name__ == '__main__':
    unittest.main()
