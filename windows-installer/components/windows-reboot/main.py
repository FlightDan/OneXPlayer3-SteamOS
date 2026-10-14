"""Decky RPC with fixed helper calls; loading the plugin has no side effects."""
import asyncio
import json

HELPER = '/usr/local/bin/oxp3-reboot-windows'


class Plugin:
    async def _main(self):
        pass

    async def _unload(self):
        pass

    async def _uninstall(self):
        pass

    async def _call(self, *args):
        try:
            process = await asyncio.create_subprocess_exec(
                HELPER, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), 60)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise RuntimeError('Request timed out. Refresh the Windows boot status. / 请求超时，请刷新启动状态。')
            reply = json.loads(output)
            if process.returncode and reply.get('ok'):
                raise RuntimeError('Windows boot helper failed')
            return reply
        except Exception as error:
            return {'ok': False, 'error': str(error)}

    async def status(self):
        return await self._call('status')

    async def manager_status(self):
        return await self._call('status-manager')

    async def reboot(self, expected, confirmed=False):
        import re
        if confirmed is not True or not isinstance(expected, str) or not re.fullmatch('[0-9A-F]{4}', expected):
            return {'ok': False, 'error': 'Confirm the restart first. / 请先确认重启。'}
        return await self._call('reboot', expected)

    async def reboot_manager(self, expected, confirmed=False):
        import re
        if confirmed is not True or not isinstance(expected, str) or not re.fullmatch('[0-9A-F]{4}', expected):
            return {'ok': False, 'error': 'Confirm the restart first. / 请先确认重启。'}
        return await self._call('reboot-manager', expected)
