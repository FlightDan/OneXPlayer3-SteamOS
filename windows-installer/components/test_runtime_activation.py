"""Regression checks for selected, guarded input service activation."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import integration_runtime as runtime


class ActivationChecks(unittest.TestCase):
    def execute_fixture(self, components, refused=False, failed=False):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'A'; directory.mkdir()
            record={'components':{name:{'status':status} for name,status in components.items()},
                    'options':{'repairs':[name for name in components if name!='system-update-policy']}}
            data={'exists':True,'uid':0,'mode':0o600,'data':base64.b64encode(json.dumps(record).encode()).decode()}
            real_path=Path
            def path(value):
                return real_path(tmp) if str(value)=='/home/.oxp3-installer/integration' else real_path(value)
            commands=[]
            def run(*args):
                commands.append(args)
                if args==('/usr/bin/inputplumber','--version'): return 'inputplumber 0.78.0'
                if failed and args==('systemctl','start','inputplumber.service'): raise RuntimeError('input service failed')
                return ''
            with patch.object(runtime,'Path',side_effect=path),patch.object(runtime,'snapshot',return_value=data), \
                 patch.object(runtime,'current_slot',return_value='A'),patch.object(runtime,'trusted_tree'), \
                 patch.object(runtime,'device_guard',side_effect=RuntimeError('incompatible target') if refused else None), \
                 patch.object(runtime,'run',side_effect=run),patch.object(runtime.os,'geteuid',return_value=0):
                result=runtime.execute()
            return result,commands

    def test_selected_input_starts_on_each_boot(self):
        for _ in range(2):
            result,commands=self.execute_fixture({'input':'files_installed'})
            self.assertIn(('systemctl','start','inputplumber.service'),commands)
            self.assertEqual(result['input']['status'],'active')

    def test_unselected_missing_or_incompatible_input_never_starts(self):
        for selected,refused in (({},False),({'input':'not_installed'},False),({'input':'files_installed'},True)):
            result,commands=self.execute_fixture(selected,refused=refused)
            self.assertNotIn(('systemctl','start','inputplumber.service'),commands)
        self.assertEqual(result['input']['status'],'refused')

    def test_start_failure_is_reported(self):
        result,_=self.execute_fixture({'input':'files_installed'},failed=True)
        self.assertEqual(result['input']['status'],'failed')
        self.assertIn('input service failed',result['input']['reason'])

    def test_legacy_update_policy_does_not_require_masks_or_block_other_activation(self):
        result,commands=self.execute_fixture({'system-update-policy':'files_installed','input':'files_installed'})
        self.assertNotIn('system-update-policy',result)
        self.assertEqual(result['input']['status'],'active')
        self.assertIn(('systemctl','start','inputplumber.service'),commands)
        self.assertFalse(any(unit in args for args in commands for unit in ('atomupd.service','rauc.service')))


if __name__=='__main__': unittest.main()
