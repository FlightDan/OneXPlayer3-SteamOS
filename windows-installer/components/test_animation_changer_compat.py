"""Exercise startup filesystem effects without importing or starting Decky.

The optional pinned ZIP check uses OXP3_ANIMATION_CHANGER_ARCHIVE, or the local
installer cache. Only the override assignment and initial directory-creation
block are executed from the upstream backend; network and animation hooks do
not run. These checks never access the user's real Steam directory.
"""
import ast
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


def load_patch():
    # The helper transforms in-memory payloads; loading only it keeps these
    # focused checks independent of the legacy Linux transaction imports.
    source = Path(__file__).with_name('plugin_installer.py').read_text(encoding='utf-8')
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'patch_animation_changer')
    namespace = {'json': json}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'plugin_installer.py', 'exec'), namespace)
    return namespace['patch_animation_changer']


patch_animation_changer = load_patch()
PREFIX = 'plugins/SDH-AnimationChanger/'
# Upstream 1.3.2's initialization ordering: no Steam bootstrap is required before
# Decky invokes this block. The real ZIP check below also exercises its own AST.
BACKEND = b'''import os
OVERRIDE_PATH = os.path.expanduser('~/.steam/root/config/uioverrides/movies')
def apply_animation(video, anim_id):
    override_path = f'{OVERRIDE_PATH}/{video}'
class Plugin:
    async def _main(self):
        try:
            os.makedirs(ANIMATIONS_PATH, exist_ok=True)
            os.makedirs(OVERRIDE_PATH, exist_ok=True)
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            os.makedirs(DOWNLOADS_PATH, exist_ok=True)
        except Exception:
            raise
'''


def payload(source=BACKEND):
    return {
        PREFIX + 'plugin.json': {'data': b'{"name":"Animation Changer"}'},
        PREFIX + 'package.json': {'data': b'{"name":"decky-animation-changer","version":"1.3.2"}'},
        PREFIX + 'main.py': {'data': source, 'mode': 0o644, 'user': False},
        PREFIX + 'LICENSE': {'data': b'Upstream BSD-3-Clause license fixture'},
    }


def run_startup_directories(source, home):
    tree = ast.parse(source)
    resolver = [node for node in tree.body if
                isinstance(node, ast.FunctionDef) and node.name == 'get_override_path' or
                isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'OVERRIDE_PATH'
                                                     for target in node.targets)]
    plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Plugin')
    main = next(node for node in plugin.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_main')
    directories = next(node for node in main.body if isinstance(node, ast.Try))
    # Execute the original startup block, preserving its real makedirs calls.
    main.body = [directories]
    plugin.body = [main]
    isolated = ast.Module(body=[*resolver, plugin], type_ignores=[])
    namespace = {
        'os': os,
        'ANIMATIONS_PATH': str(home / 'homebrew/data/animations'),
        'DOWNLOADS_PATH': str(home / 'homebrew/data/downloads'),
        'CONFIG_PATH': str(home / 'homebrew/settings/config.json'),
    }
    with patch.dict(os.environ, {'HOME': str(home)}):
        exec(compile(isolated, 'deployed-main.py', 'exec'), namespace)
        asyncio.run(namespace['Plugin']()._main())


@unittest.skipUnless(os.name == 'posix' and shutil.which('ln'), 'Requires real Unix symlink semantics')
class SteamBootstrapChecks(unittest.TestCase):
    def bootstrap(self, home):
        steam = home / '.local/share/Steam'
        steam.mkdir(parents=True, exist_ok=True)
        (home / '.steam').mkdir(exist_ok=True)
        subprocess.run(['ln', '-sfn', str(steam), str(home / '.steam/root')], check=True)
        return steam

    def verify_source(self, source):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original_home = base / 'original'; original_home.mkdir()
            fixed_home = base / 'fixed'; fixed_home.mkdir()
            run_startup_directories(source, original_home)
            # Control reproduces the malformed root and nested Steam link.
            self.assertTrue((original_home / '.steam/root').is_dir())
            self.assertFalse((original_home / '.steam/root').is_symlink())
            self.bootstrap(original_home)
            self.assertTrue((original_home / '.steam/root/Steam').is_symlink())

            files = payload(source)
            changed = patch_animation_changer(files, PREFIX)
            deployed = changed[PREFIX + 'main.py']['data']
            compile(deployed, 'deployed-main.py', 'exec')
            run_startup_directories(deployed, fixed_home)
            self.assertFalse(os.path.lexists(fixed_home / '.steam/root'))
            self.assertTrue((fixed_home / '.local/share/Steam/config/uioverrides/movies').is_dir())
            canonical = self.bootstrap(fixed_home)
            root = fixed_home / '.steam/root'
            self.assertTrue(root.is_symlink())
            self.assertEqual(root.resolve(), canonical)
            self.assertFalse(os.path.lexists(root / 'Steam'))
            self.assertEqual((root / 'config/uioverrides/movies').resolve(),
                             canonical / 'config/uioverrides/movies')

    def test_deployed_backend_preserves_steam_bootstrap_link(self):
        self.verify_source(BACKEND)

    def test_real_pinned_archive_backend_preserves_steam_bootstrap_link(self):
        archive = Path(os.environ.get('OXP3_ANIMATION_CHANGER_ARCHIVE',
                       Path(__file__).resolve().parents[1] / 'cache/plugins/animation-changer/animation-changer-1.3.2.zip'))
        if not archive.is_file(): self.skipTest('Pinned upstream ZIP not available')
        original_zip = archive.read_bytes()
        with zipfile.ZipFile(archive) as package:
            files = {PREFIX + name.split('/', 1)[1]: {'data': package.read(name)}
                     for name in package.namelist() if not name.endswith('/')}
        changed = patch_animation_changer(files, PREFIX)
        self.assertEqual(changed[PREFIX + 'LICENSE'], files[PREFIX + 'LICENSE'])
        self.verify_source(files[PREFIX + 'main.py']['data'])
        self.assertEqual(archive.read_bytes(), original_zip)

    def test_existing_custom_directory_and_live_or_dangling_symlinks_are_preserved(self):
        source = patch_animation_changer(payload(), PREFIX)[PREFIX + 'main.py']['data']
        for kind in ('directory', 'live', 'dangling'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                root = home / '.steam/root'
                root.parent.mkdir()
                custom = home / 'custom-steam'
                if kind == 'directory':
                    root.mkdir()
                    expected = root
                else:
                    if kind == 'live': custom.mkdir()
                    root.symlink_to(custom, target_is_directory=True)
                    expected = custom
                run_startup_directories(source, home)
                self.assertEqual(root.is_symlink(), kind != 'directory')
                self.assertTrue((expected / 'config/uioverrides/movies').is_dir())
                self.assertFalse((home / '.local/share/Steam').exists())

    def test_apply_resolves_steam_root_again_after_startup(self):
        source = patch_animation_changer(payload(), PREFIX)[PREFIX + 'main.py']['data']
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_startup_directories(source, home)
            root = home / '.steam/root'
            root.parent.mkdir(exist_ok=True)
            custom = home / 'new-steam'
            root.symlink_to(custom, target_is_directory=True)
            tree = ast.parse(source)
            isolated = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                                        and node.name in ('get_override_path', 'apply_animation')], type_ignores=[])
            namespace = {'os': os}
            with patch.dict(os.environ, {'HOME': str(home)}):
                exec(compile(isolated, 'deployed-main.py', 'exec'), namespace)
                namespace['apply_animation']('deck_startup.webm', '')
            self.assertTrue(root.is_symlink())
            self.assertTrue((custom / 'config/uioverrides/movies').is_dir())


class CompatibilityGuardChecks(unittest.TestCase):
    def test_only_backend_bytes_change_and_file_metadata_is_preserved(self):
        files = payload()
        changed = patch_animation_changer(files, PREFIX)
        self.assertIsNot(changed, files)
        self.assertEqual(files[PREFIX + 'main.py']['data'], BACKEND)
        self.assertEqual(changed[PREFIX + 'main.py']['mode'], 0o644)
        self.assertIs(changed[PREFIX + 'main.py']['user'], False)
        for name in files:
            if name != PREFIX + 'main.py': self.assertEqual(changed[name], files[name])
        source = changed[PREFIX + 'main.py']['data']
        self.assertNotIn(b'OVERRIDE_PATH', source)
        self.assertIn(b'os.path.lexists(steam_root)', source)
        self.assertIn(b'os.path.realpath(steam_root)', source)

    def test_prior_canonical_patch_updates_to_the_same_resolver(self):
        prior = BACKEND.replace(b'~/.steam/root/config/uioverrides/movies',
                                b'~/.local/share/Steam/config/uioverrides/movies')
        self.assertEqual(patch_animation_changer(payload(prior), PREFIX)[PREFIX + 'main.py']['data'],
                         patch_animation_changer(payload(), PREFIX)[PREFIX + 'main.py']['data'])

    def test_unsupported_identity_version_and_source_are_refused_before_mutation(self):
        variants = [
            ('plugin.json', b'{"name":"Other Plugin"}'),
            ('plugin.json', b'[]'),
            ('package.json', b'null'),
            ('package.json', b'{"name":"other","version":"1.3.2"}'),
            ('package.json', b'{"name":"decky-animation-changer","version":"1.3.3"}'),
            ('main.py', BACKEND.replace(b'OVERRIDE_PATH =', b'OVERRIDE_PATH=')),
            ('main.py', BACKEND + BACKEND),
        ]
        for relative, data in variants:
            with self.subTest(relative=relative, data=data[:60]):
                files = payload(); files[PREFIX + relative] = {'data': data}
                before = {name: dict(entry) for name, entry in files.items()}
                with self.assertRaisesRegex(RuntimeError, 'Unsupported Animation Changer'):
                    patch_animation_changer(files, PREFIX)
                self.assertEqual(files, before)

    def test_missing_runtime_input_is_refused(self):
        files = payload(); del files[PREFIX + 'main.py']
        with self.assertRaisesRegex(RuntimeError, 'Missing Animation Changer'):
            patch_animation_changer(files, PREFIX)


if __name__ == '__main__': unittest.main()
