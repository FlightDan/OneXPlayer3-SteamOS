import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cpu_control as cpu

class CPUControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name);self.paths={}
        for key,maximum in [('p',4700000),('e',3600000),('lp',3100000)]:
            p=base/key;p.mkdir();self.paths[key]=[p]
            fields={'scaling_min_freq':'400000','cpuinfo_max_freq':str(maximum),'scaling_max_freq':str(maximum),
                    'energy_performance_available_preferences':'performance balance_performance balance_power power',
                    'energy_performance_preference':'balance_performance','scaling_governor':'powersave'}
            for name,value in fields.items():(p/name).write_text(value)
        for name,value in [('CONFIG',base/'config.json'),('STATE',base/'state.json')]:
            p=patch.object(cpu,name,value);p.start();self.addCleanup(p.stop)
        for p in (patch.object(cpu,'groups',return_value=self.paths),patch.object(cpu,'status',return_value={}),patch.object(cpu.fcntl,'flock')):
            p.start();self.addCleanup(p.stop)
        cpu.CONFIG.write_text(json.dumps({'enabled':False}))
        self.config={'enabled':True,'epp':'balance_power','p_mhz':3000,'e_mhz':2500,'lp_mhz':1800}
        self.original={str(p/name):(p/name).read_text() for paths in self.paths.values() for p in paths for name in ('scaling_max_freq','energy_performance_preference')}

    def assert_original(self):
        self.assertEqual({k:Path(k).read_text().strip() for k in self.original},self.original)

    def test_repeated_apply_then_restore_preserves_initial_baseline(self):
        cpu.apply(self.config)
        cpu.apply({**self.config,'p_mhz':3200})
        cpu.apply({'enabled':False})
        self.assert_original()
        self.assertFalse(cpu.STATE.exists())

    def test_partial_failure_rolls_back_every_attribute(self):
        writer=cpu.write_verified
        def fail(name,value):
            if Path(name).parent.name=='e' and Path(name).name=='scaling_max_freq' and value=='2500000':raise OSError('injected')
            writer(name,value)
        with patch.object(cpu,'write_verified',side_effect=fail),self.assertRaisesRegex(RuntimeError,'rollback=verified'):
            cpu.apply(self.config)
        self.assert_original()
        self.assertFalse(cpu.STATE.exists())

    def test_crash_after_partial_write_retains_recovery_intent(self):
        writer=cpu.write_verified;calls=0
        def crash(name,value):
            nonlocal calls
            writer(name,value);calls+=1
            if calls==1:raise SystemExit('crash')
        with patch.object(cpu,'write_verified',side_effect=crash),self.assertRaises(SystemExit):cpu.apply(self.config)
        self.assertTrue(cpu.STATE.exists())
        cpu.restore()
        self.assert_original()

    def test_restore_preserves_external_frequency_change(self):
        cpu.apply(self.config)
        changed=self.paths['p'][0]/'scaling_max_freq';changed.write_text('2800000')
        result=cpu.restore()
        self.assertIn(str(changed),result['external_changes'])
        self.assertEqual(changed.read_text(),'2800000')

    def test_rejects_invalid_frequency_and_epp_before_writes(self):
        for value in ({**self.config,'p_mhz':4800},{**self.config,'e_mhz':True},
                      {**self.config,'epp':'not-real'},{**self.config,'lp_mhz':350},{**self.config,'enabled':1}):
            with self.subTest(value=value),self.assertRaises(ValueError):cpu.apply(value)
            self.assert_original()

    def test_performance_governor_conflict_is_not_silently_changed(self):
        p=self.paths['p'][0]/'scaling_governor';p.write_text('performance')
        with self.assertRaisesRegex(ValueError,'governor'):cpu.apply(self.config)
        self.assert_original()
        self.assertEqual(p.read_text(),'performance')

if __name__=='__main__':unittest.main()
