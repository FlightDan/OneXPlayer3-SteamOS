import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('telemetry',Path(__file__).with_name('telemetry.py'))
m=importlib.util.module_from_spec(spec)
with patch('os.getuid',return_value=1000,create=True):spec.loader.exec_module(m)

class PmtGpuTests(unittest.TestCase):
    def test_energy_delta_and_rebaseline(self):
        old=(163840,'pmtA',10.,100.)
        self.assertEqual(m.pmt_gpu_watts((491520,'pmtA',11.,101.),old),20.)
        for current in [(491520,'pmtB',11.,101.),(0,'pmtA',11.,101.),
                        (491520,'pmtA',10.,101.),(491520,'pmtA',14.,104.),
                        (491520,'pmtA',11.,161.),(4915200,'pmtA',11.,101.)]:
            self.assertIsNone(m.pmt_gpu_watts(current,old))
        self.assertIsNone(m.pmt_gpu_watts(old,None))
        self.assertEqual(m.pmt_gpu_watts((163840,'pmtA',11.,101.),old),0.)
        # Keep all64 bits; no float subtraction of the cumulative counter.
        old=(2**60,'pmtA',10.,100.)
        self.assertEqual(m.pmt_gpu_watts((2**60+16384,'pmtA',11.,101.),old),1.)

    @unittest.skipUnless(hasattr(os,'pread'),'Linux pread required')
    def test_guid_discovery_and_failures(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            def node(name,guid,size,raw):
                p=root/name;p.mkdir()
                (p/'guid').write_text(guid);(p/'size').write_text(str(size))
                (p/'telem').write_bytes(bytes(1640)+raw.to_bytes(8,'little'))
                return p
            live=node('telem9','0x3086000',3352,2**40+123)
            node('telem2','0x3086100',744,999)
            with patch.object(m,'Path',return_value=root):
                self.assertEqual(m.pmt_gpu_counter(),(2**40+123,str(live.resolve())))
                (live/'telem').write_bytes(bytes(1644))
                with self.assertRaises(ValueError):m.pmt_gpu_counter()
                node('telem10','0x3086000',3352,1)
                with self.assertRaises(ValueError):m.pmt_gpu_counter()
                (live/'guid').write_text('0x3086100')
                (root/'telem10'/'size').write_text('3351')
                with self.assertRaises(ValueError):m.pmt_gpu_counter()

if __name__=='__main__':unittest.main()
