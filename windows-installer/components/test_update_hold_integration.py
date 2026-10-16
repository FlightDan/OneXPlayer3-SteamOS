"""Mandatory update-hold wiring tests; no service activation or device access."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_update_hold as hold_checks

COMPONENTS = hold_checks.COMPONENTS

sys.path.insert(0, str(COMPONENTS))
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('integration_product', HERE/'integration.py')
candidate = importlib.util.module_from_spec(spec)
if os.name == 'nt':
    # Only import portability: Windows runs the preflight-before-write case.
    # Actual FileTransaction/apply/restore cases require Linux root below.
    with patch.dict(sys.modules, {'fcntl': SimpleNamespace()}): spec.loader.exec_module(candidate)
else:
    spec.loader.exec_module(candidate)


class WiringChecks(unittest.TestCase):
    put = hold_checks.CandidateChecks.put
    link = hold_checks.CandidateChecks.link
    snapshot = hold_checks.CandidateChecks.snapshot

    @classmethod
    def setUpClass(cls):
        cls.payload_temp = tempfile.TemporaryDirectory()
        cls.payload = Path(cls.payload_temp.name)
        shutil.copytree(COMPONENTS, cls.payload/'components',
                        ignore=shutil.ignore_patterns('__pycache__', 'test_*.py'))
        (cls.payload/'integration').mkdir()
        if os.name == 'posix':
            from test_integration import copy_maintenance_fixture
            copy_maintenance_fixture(cls.payload)
        shutil.copyfile(HERE/'update_hold.py', cls.payload/'components/update_hold.py')
        shutil.copyfile(HERE/'integration.py', cls.payload/'components/integration.py')
        # The product runs on Linux. Keep this unchanged catalog readable by
        # Windows' default text codec for the portable preflight-order test.
        catalog = json.loads((COMPONENTS/'options.json').read_text(encoding='utf-8'))
        (cls.payload/'components/options.json').write_text(json.dumps(catalog), encoding='ascii')

    @classmethod
    def tearDownClass(cls): cls.payload_temp.cleanup()

    def setUp(self):
        hold_checks.CandidateChecks.setUp(self)
        self.put('etc/passwd', b'deck:x:1000:1000::/home/deck:/bin/bash\n')
        self.options = {'schema':1, 'repairs':[], 'plugins':[],
                        'installer_language':'en-US', 'kde_language':'system'}

    def test_hold_preflight_failure_precedes_every_stage_write(self):
        before = self.snapshot()
        with patch.object(candidate, 'update_hold_files', side_effect=RuntimeError('hold preflight refused')), \
             patch.object(candidate.os, 'geteuid', return_value=0, create=True), \
             patch.object(candidate, 'ensure_directory') as ensure, \
             patch.object(candidate, 'ensure_user_directory') as user_ensure, \
             patch.object(candidate, 'atomic_write') as write, \
             patch.object(candidate, 'apply_files') as apply:
            with self.assertRaisesRegex(RuntimeError, 'hold preflight refused'):
                candidate.stage(self.root, self.payload, self.options, 'A')
            ensure.assert_not_called(); user_ensure.assert_not_called()
            write.assert_not_called(); apply.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'Actual integration staging requires Linux root')
    def test_mandatory_hold_apply_failure_cannot_be_optional_skip(self):
        with patch.object(candidate, 'apply_files', side_effect=RuntimeError('mandatory hold apply failed')) as apply, \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'mandatory hold apply failed'):
                candidate.stage(self.root, self.payload, self.options, 'A')
            self.assertEqual(apply.call_args.args[2], 'system-update-hold')
        self.assertFalse((self.root/'home/.oxp3-installer/integration/A/result.json').exists())

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'Actual integration stage and runtime restore require Linux root')
    def test_both_slot_reports_runtime_and_real_journal_restore(self):
        other_temp = tempfile.TemporaryDirectory(); self.addCleanup(other_temp.cleanup)
        other = Path(other_temp.name)
        shutil.copytree(self.root, other, symlinks=True, dirs_exist_ok=True)
        before = self.snapshot()
        for root, slot in ((self.root, 'A'), (other, 'B')):
            with redirect_stdout(io.StringIO()), patch.object(candidate.subprocess, 'run') as run:
                result = candidate.stage(root, self.payload, self.options, slot)
                run.assert_not_called()
            report = result['components']['system-update-hold']
            self.assertEqual(report['status'], 'files_installed')
            self.assertEqual(report['os_image_updates'], 'held')
            self.assertEqual(report['steam_client_updates'], 'unchanged')
            self.assertEqual(report['activation'], 'next-boot')
            self.assertIn('offline', report['restore'])
            self.assertEqual(len(report['files']), 18)
            state = root/'home/.oxp3-installer/integration'/slot
            self.assertTrue((state/'system-update-hold/state.json').is_file())
            runtime = root/'usr/local/lib/oxp3-integration'
            self.assertEqual((runtime/'update_hold.py').read_bytes(), (HERE/'update_hold.py').read_bytes())
            self.assertEqual((runtime/'integration.py').read_bytes(), (HERE/'integration.py').read_bytes())
            # Exercise the installed runtime in a fresh isolated Python process.
            # This catches missing update_hold imports on the actual restore path.
            restored = subprocess.run([sys.executable, '-I', '-B', str(runtime/'integration.py'), 'restore',
                                       '--root', str(root), '--slot', slot, '--component', 'system-update-hold'],
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(json.loads(restored.stdout), [])
            self.assertFalse((root/hold_checks.hold.DROPIN).exists())
            recorded = json.loads((state/'result.json').read_text())
            self.assertEqual(recorded['components']['system-update-hold']['status'], 'restored')
        for relative, value in before.items():
            if value[0] == 'file': self.assertEqual((self.root/relative).read_bytes(), value[1])
            else: self.assertEqual(os.readlink(self.root/relative), value[1])


if __name__ == '__main__': unittest.main()
