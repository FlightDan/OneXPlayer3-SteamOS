"""Decky RPC boundary. No root flag, shell RPC or writes on plugin load."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from manager import Manager


class Plugin:
    async def _main(self):
        if hasattr(self, 'manager'):
            return
        self.manager = Manager()
        self.lock = asyncio.Lock()
        self.install_active = False

    async def _unload(self):
        # Active launchers and backups are independent of the plugin directory.
        pass

    async def _uninstall(self):
        # Do not restore files behind a running game or discard retained backups.
        pass

    async def _call(self, name, *args):
        if not hasattr(self, 'manager'):
            await self._main()
        if (name == 'opti_install' and self.lock.locked()) or (name not in ('inventory', 'inspect_game') and (self.install_active or self.manager.progress.snapshot()['running'])):
            return {'ok': False, 'error': 'Opti 操作仍在进行，请等待完成。'}
        async with self.lock:
            installing = name == 'opti_install'
            if installing: self.install_active = True
            try:
                return {'ok': True, 'data': await asyncio.to_thread(getattr(self.manager, name), *args)}
            except Exception as error:
                message = str(error)
                if 'Game is running' in message or 'Prefix is in use' in message:
                    message = '游戏仍在运行。请从 Steam 退出游戏，再操作 XMX 开关。'
                return {'ok': False, 'error': message}
            finally:
                if installing: self.install_active = False

    async def operation_progress(self):
        if not hasattr(self, 'manager'):
            await self._main()
        # Download work owns the ordinary RPC lock; snapshots must bypass it.
        return {'ok': True, 'data': self.manager.progress.snapshot()}

    async def inventory(self):
        return await self._call('inventory')

    async def inspect_game(self, appid):
        return await self._call('inspect_game', appid)

    async def enable(self, appid, executable, route, old_launch):
        return await self._call('enable', appid, executable, route, old_launch)

    async def confirm_launch(self, appid, actual):
        return await self._call('confirm_launch', appid, actual)

    async def restore(self, appid, actual):
        return await self._call('restore', appid, actual)

    async def opti_install(self, appid, executable, actual, version, source):
        return await self._call('opti_install', appid, executable, actual, version, source)

    async def opti_migrate(self, appid, executable, actual):
        return await self._call('opti_migrate', appid, executable, actual)

    async def opti_rollback(self, appid, actual):
        return await self._call('opti_rollback', appid, actual)

    async def opti_uninstall(self, appid, actual):
        return await self._call('opti_uninstall', appid, actual)

    async def opti_confirm(self, appid, actual):
        return await self._call('opti_confirm', appid, actual)

    async def opti_toggle(self, appid, enabled, actual):
        return await self._call('opti_toggle', appid, enabled, actual)

    async def opti_settings(self, appid, settings, reset=False):
        return await self._call('opti_settings', appid, settings, reset)

    async def opti_panel(self, appid):
        return await self._call('opti_panel', appid)
