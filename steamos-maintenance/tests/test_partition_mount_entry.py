"""Direct desktop entry points never elevate the persistent-mount UI."""
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import cli
from oxp3_maintenance.desktop_service import DesktopService
from oxp3_maintenance.touch_ui import TouchWindow


class PartitionMountEntryTests(unittest.TestCase):
    def test_bash_action_is_registered_and_dispatches_without_a_privileged_probe(self):
        args = cli.parser().parse_args(['partition-mount'])
        with mock.patch.object(cli, 'launch_partition_mount', return_value={'status': 'closed'}) as launch, \
             mock.patch('oxp3_maintenance.probe.live', side_effect=AssertionError('must not probe')):
            self.assertEqual(cli.dispatch(args), {'status': 'closed'})
        launch.assert_called_once_with()

    def test_desktop_service_uses_the_unprivileged_launcher_and_localized_install_guidance(self):
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(Path, 'home', return_value=Path(temporary)), \
             mock.patch.object(cli, 'installed_release', return_value={'version': '1.0.0', 'channel': 'stable'}):
            service = DesktopService(SimpleNamespace(bundle=None, bundle_dir=None), language='zh')
            with mock.patch.object(cli, 'launch_partition_mount') as launch:
                view = service.perform('partition-mount')
        launch.assert_called_once()
        guidance = launch.call_args.kwargs['missing_message']
        self.assertIn('修复与插件', guidance)
        self.assertIn('KDE 图形分区持久挂载', guidance)
        self.assertEqual(view['heading'], 'OXP3 修复与项目更新')

    def test_overview_action_uses_the_existing_sequential_worker(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.perform = mock.Mock()
        TouchWindow._start_partition_mount(ui)
        ui.perform.assert_called_once_with('partition-mount', route='overview')


class TrustedPartitionMountLaunchTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path('/trusted/home/.oxp3-partition-mount')
        self.files = {name: self.directory / name for name in (
            'desktop.py', 'mounts.py', 'oxp3-partition-mount')}
        self.symlinks, self.writable, self.missing = set(), set(), set()
        patcher = mock.patch.object(cli, 'PARTITION_MOUNT_HOME', self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cli.Path, 'lstat', autospec=True, side_effect=self.fake_lstat)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_lstat(self, path):
        if path in self.missing:
            raise FileNotFoundError(str(path))
        if path in self.symlinks:
            mode = stat.S_IFLNK | 0o777
        elif path in self.files.values():
            mode = stat.S_IFREG | (0o755 if path == self.files['oxp3-partition-mount'] else 0o644)
        else:
            mode = stat.S_IFDIR | 0o755
        if path in self.writable:
            mode |= 0o002
        return SimpleNamespace(st_uid=0, st_mode=mode)

    def test_launch_validates_code_and_waits_for_desktop_window(self):
        result = SimpleNamespace(returncode=0, stderr='')
        with mock.patch.object(cli.os, 'name', 'posix'), \
             mock.patch.object(cli.os, 'geteuid', return_value=1000, create=True), \
             mock.patch.object(cli.subprocess, 'run', return_value=result) as run:
            self.assertEqual(cli.launch_partition_mount(), {'status': 'partition_mount_closed'})
        command = run.call_args.args[0]
        self.assertEqual(command, ['/usr/bin/python3', '-I', '-B', str(self.files['desktop.py'])])
        self.assertNotIn('pkexec', command)
        self.assertEqual(run.call_args.kwargs['stdin'], cli.subprocess.DEVNULL)
        self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_code_files_and_ancestors_reject_symlinks_and_writable_paths(self):
        for name, path in self.files.items():
            with self.subTest(name=name):
                self.symlinks.add(path)
                with self.assertRaisesRegex(RuntimeError, 'Untrusted Partition Mount program path'):
                    cli._trusted_partition_mount_scripts()
                self.symlinks.clear()
                self.writable.add(path)
                with self.assertRaisesRegex(RuntimeError, 'Untrusted Partition Mount program path'):
                    cli._trusted_partition_mount_scripts()
                self.writable.clear()
        self.symlinks.add(self.directory.parent)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted Partition Mount program path'):
            cli._trusted_partition_mount_scripts()

    def test_missing_component_gives_install_guidance_and_child_failure_returns(self):
        self.missing.add(self.files['mounts.py'])
        with mock.patch.object(cli.os, 'name', 'posix'), \
             mock.patch.object(cli.os, 'geteuid', return_value=1000, create=True):
            with self.assertRaisesRegex(RuntimeError, 'Repairs & plugins'):
                cli.launch_partition_mount()

        self.missing.clear()
        with mock.patch.object(cli.os, 'name', 'posix'), \
             mock.patch.object(cli.os, 'geteuid', return_value=1000, create=True), \
             mock.patch.object(cli.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='dialog failed')):
            with self.assertRaisesRegex(RuntimeError, 'dialog failed'):
                cli.launch_partition_mount()


if __name__ == '__main__':
    unittest.main()
