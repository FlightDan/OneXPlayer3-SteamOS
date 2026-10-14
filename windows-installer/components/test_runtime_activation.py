"""Regression checks for selected, guarded input service activation."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import integration_runtime as runtime


class ActivationChecks(unittest.TestCase):
    def execute_fixture(self, components, refused=False, failed=False, unpaused=False):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'A'; directory.mkdir()
            record={'components':{name:{'status':status} for name,status in components.items()},
                    'options':{'repairs':list(components)}}
            data={'exists':True,'uid':0,'mode':0o600,'data':base64.b64encode(json.dumps(record).encode()).decode()}
            real_path=Path
            def path(value):
                return real_path(tmp) if str(value)=='/home/.oxp3-installer/integration' else real_path(value)
            commands=[]
            def run(*args):
                commands.append(args)
                if args==('/usr/bin/inputplumber','--version'): return 'inputplumber 0.78.0'
                if args[:2]==('systemctl','show'): return 'loaded' if unpaused else 'masked'
                if failed and args==('systemctl','start','inputplumber.service'): raise RuntimeError('input service failed')
                return ''
            with patch.object(runtime,'Path',side_effect=path),patch.object(runtime,'snapshot',return_value=data), \
                 patch.object(runtime,'current_slot',return_value='A'),patch.object(runtime,'trusted_tree'), \
                 patch.object(runtime,'device_guard',side_effect=RuntimeError('incompatible target') if refused else None), \
                 patch.object(runtime,'run',side_effect=run),patch.object(runtime,'verify_update_policy'),patch.object(runtime.os,'geteuid',return_value=0):
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

    def test_update_policy_checks_effective_units_and_reports_unpaused_service(self):
        result,commands=self.execute_fixture({'system-update-policy':'files_installed'})
        self.assertEqual(result['system-update-policy']['status'],'ready')
        for unit in ('atomupd.service','rauc.service'):
            self.assertIn(('systemctl','show',unit,'-p','LoadState','--value'),commands)
        result,_=self.execute_fixture({'system-update-policy':'files_installed'},unpaused=True)
        self.assertEqual(result['system-update-policy']['status'],'refused')
        self.assertIn('not paused',result['system-update-policy']['reason'])


if __name__=='__main__': unittest.main()
