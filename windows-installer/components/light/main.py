"""Decky entrypoint for OXP3 Light. See THIRD_PARTY_NOTICES.md for authors and licenses."""
import asyncio
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("oxp3_light_control", Path(__file__).with_name("light_control.py"))
_light = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_light)
_controller = _light.LightController()


class Plugin:
    async def get_status(self):
        return await asyncio.to_thread(_controller.status)

    async def set_zone(self, zone, config):
        return await asyncio.to_thread(_controller.set_zone, zone, config)

    async def _main(self):
        pass  # Preserve firmware lights on load; no automatic replay.

    async def _unload(self):
        pass  # Preserve the user's last lighting state.
