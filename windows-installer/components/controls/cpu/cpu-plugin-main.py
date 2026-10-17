import importlib.util
import asyncio
import json
import subprocess

spec=importlib.util.spec_from_file_location('oxp3_cpu','/var/lib/oxp3-cpu/cpu_control.py')
cpu=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpu)

power_spec=importlib.util.spec_from_file_location('oxp3_power','/var/lib/oxp3-cpu/power_control.py')
power=importlib.util.module_from_spec(power_spec)
power_spec.loader.exec_module(power)

class Plugin:
    async def get_power_status(self):
        return await asyncio.to_thread(power.request, 'status')

    async def set_pl1(self, watts):
        return await asyncio.to_thread(power.request, 'set-pl1', watts)

    async def set_pl2(self, watts):
        return await asyncio.to_thread(power.request, 'set-pl2', watts)

    async def get_status(self):
        return cpu.status()

    async def configure(self, config):
        cpu.targets(config)
        previous=json.loads(cpu.CONFIG.read_text())
        cpu.atomic(cpu.CONFIG,config)
        try:
            subprocess.run(['systemctl','restart','oxp3-cpu.service'],check=True,capture_output=True,text=True,timeout=20)
        except Exception as error:
            cpu.atomic(cpu.CONFIG,previous)
            recovery=subprocess.run(['systemctl','start','oxp3-cpu.service'],capture_output=True,text=True,timeout=20)
            raise RuntimeError(f'CPU setting failed: {error}; previous configuration restart={recovery.returncode}') from error
        return cpu.status()

    async def restore(self):
        previous=json.loads(cpu.CONFIG.read_text())
        previous['enabled']=False
        return await self.configure(previous)

    async def _main(self):
        pass

    async def _unload(self):
        # Plugin removal/reload must not leave a hidden CPU restriction active.
        config=json.loads(cpu.CONFIG.read_text()); config['enabled']=False
        cpu.atomic(cpu.CONFIG,config)
        cpu.restore()
