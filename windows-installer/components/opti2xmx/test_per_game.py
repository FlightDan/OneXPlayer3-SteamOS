"""Failure-path tests only: fake staged files do not establish GPU/game acceptance."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("per_game", Path(__file__).with_name("per_game.py"))
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prefix = self.root / "prefix"
        (self.prefix / "drive_c/windows/system32").mkdir(parents=True)
        self.package = self.root / "release with ' quotes $(touch BAD)"
        for name in ("igdext64.dll", "lib/libvulkan_intel.so", "tools/cm-compile.sh", "tools/cmk_pack.py",
                     "igc/neo/bin/ocloc", "igc/igc/local/lib/libigc.so"):
            target = self.package / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("staged fixture " + name)
        (self.package / "tools/cm-compile.sh").chmod(0o700)
        (self.package / "tools/cmk_pack.py").write_text("# fixture Python packer\n")
        (self.package / "igc/neo/bin/ocloc").chmod(0o700)
        self.state = self.root / "state with ' quotes"
        self.dll = self.prefix / tool.DLL_REL
        self.args = argparse.Namespace(prefix=str(self.prefix), package=str(self.package), state=str(self.state),
                                       game_exe="FixtureGameUnique.exe", config=None)

    def tearDown(self):
        self.temp.cleanup()

    def install(self):
        # The CI/container fixture account can be root. Bypass only the independent
        # ordinary-account gate here; real ownership checks still use the fixture UID.
        with contextlib.redirect_stdout(io.StringIO()), patch.object(tool, "ordinary_user"):
            tool.install(self.args)

    def restore(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(tool, "ordinary_user"):
            tool.restore(argparse.Namespace(state=str(self.state)))

    def test_original_absence_and_created_directories_are_restored(self):
        self.install()
        self.assertTrue(self.dll.is_file())
        self.restore()
        self.assertFalse(os.path.lexists(self.dll))
        self.assertFalse(self.dll.parent.exists())
        self.assertFalse(self.state.joinpath("game.conf").exists())
        self.assertEqual(tool.load(self.state)["status"], "restored")
        self.assertTrue(Path(tool.load(self.state)["last_archive"]).is_dir())
        self.restore()  # Recovery is idempotent; backups remain available.

    def test_existing_wine_directory_case_is_reused_and_absence_restored(self):
        actual = self.prefix / "drive_c/Opti2XMX-Driver/igdext64.dll"
        actual.parent.mkdir(parents=True)
        self.install()
        self.assertTrue(actual.is_file())
        self.assertFalse((self.prefix / "drive_c/opti2xmx-driver").exists())
        self.assertEqual(tool.recorded_dll_path(tool.load(self.state)), actual)
        self.restore()
        self.assertFalse(actual.exists())
        self.assertTrue(actual.parent.is_dir())

    def test_windows_system32_spelling_is_accepted(self):
        windows = self.prefix / "drive_c/windows"
        windows.rename(windows.with_name("Windows"))
        system32 = self.prefix / "drive_c/Windows/system32"
        system32.rename(system32.with_name("System32"))
        self.install()
        actual = self.prefix / "drive_c/opti2xmx-driver/igdext64.dll"
        self.assertTrue(actual.is_file())
        self.assertFalse((self.prefix / "drive_c/windows").exists())
        self.restore()
        self.assertFalse(actual.exists())

    def test_dotdot_recorded_dll_path_refuses(self):
        with self.assertRaisesRegex(RuntimeError, "original prefix"):
            tool.recorded_dll_path(dict(prefix=str(self.prefix), files=[dict(label="igdext64.dll",path=str(self.prefix / ".." / "elsewhere.dll"))]))

    def test_existing_cased_dll_content_and_metadata_are_restored(self):
        actual = self.prefix / "drive_c/Opti2XMX-Driver/IGDEXT64.DLL"
        actual.parent.mkdir(parents=True)
        actual.write_bytes(b"original cased DLL")
        actual.chmod(0o640)
        os.utime(actual, ns=(1_700_000_000_000_000_000, 1_700_000_001_000_000_000))
        original_mtime = actual.stat().st_mtime_ns
        self.install()
        self.assertNotEqual(actual.read_bytes(), b"original cased DLL")
        self.restore()
        self.assertEqual(actual.read_bytes(), b"original cased DLL")
        self.assertEqual(actual.stat().st_mode & 0o777, 0o640)
        self.assertEqual(actual.stat().st_mtime_ns, original_mtime)

    def test_ambiguous_case_directories_refuse_before_backups_or_writes(self):
        parent = self.prefix / "drive_c"
        (parent / "Opti2XMX-Driver").mkdir()
        (parent / "opti2xmx-driver").mkdir()
        with self.assertRaisesRegex(RuntimeError, "Ambiguous Windows path"):
            self.install()
        self.assertFalse(self.state.exists())
        self.assertFalse((self.prefix / tool.OWNER_REL).exists())

    def test_external_recorded_dll_path_refuses(self):
        with self.assertRaisesRegex(RuntimeError, "original prefix"):
            tool.recorded_dll_path(dict(prefix=str(self.prefix), files=[dict(label="igdext64.dll",path=str(self.root / "elsewhere.dll"))]))

    def test_original_file_config_and_stock_cache_survive(self):
        self.dll.parent.mkdir(parents=True)
        self.dll.write_bytes(b"original DLL\x00")
        self.dll.chmod(0o640)
        stock = self.dll.with_name("igdext64.dll.stock")
        stock.write_text("preexisting stock backup")
        config = self.root / "configs/game-123.conf"
        config.parent.mkdir()
        config.write_text("export EXISTING=preserve\n")
        self.args.config = str(config)
        kernels = self.prefix / "drive_c/igdext_kernels"
        kernels.mkdir()
        (kernels / "map.txt").write_text("prior kernel map")
        self.install()
        (kernels / "new-diagnostic.txt").write_text("new evidence")
        (self.state / "cache/new-cache-file").write_text("cached binary fixture")
        self.restore()
        self.assertEqual(self.dll.read_bytes(), b"original DLL\x00")
        self.assertEqual(self.dll.stat().st_mode & 0o777, 0o640)
        self.assertEqual(config.read_text(), "export EXISTING=preserve\n")
        self.assertEqual(stock.read_text(), "preexisting stock backup")
        self.assertEqual((kernels / "map.txt").read_text(), "prior kernel map")
        self.assertTrue((kernels / "new-diagnostic.txt").exists())
        archive = Path(tool.load(self.state)["last_archive"])
        self.assertTrue((archive / "igdext_kernels/new-diagnostic.txt").exists())
        self.assertTrue((archive / "cache/new-cache-file").exists())
        initial = Path(tool.load(self.state)["initial_archive"])
        self.assertEqual((initial / "igdext_kernels/map.txt").read_text(), "prior kernel map")

    def test_symlink_file_restores_without_overwriting_link_target(self):
        self.dll.parent.mkdir(parents=True)
        original = self.root / "linked-original"
        original.write_text("do not overwrite external target")
        self.dll.symlink_to(original)
        self.install()
        self.assertFalse(self.dll.is_symlink())
        self.restore()
        self.assertTrue(self.dll.is_symlink())
        self.assertEqual(os.readlink(self.dll), str(original))
        self.assertEqual(original.read_text(), "do not overwrite external target")

    def test_install_failure_restores_before_state(self):
        self.dll.parent.mkdir(parents=True)
        self.dll.write_text("original")
        atomic = tool.atomic_text
        failed = False

        def fail_once(path, text, mode=0o600):
            nonlocal failed
            if path == self.state / "game.conf" and not failed:
                failed = True
                raise OSError("simulated full disk writing config")
            return atomic(path, text, mode)

        with patch.object(tool, "atomic_text", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "original files restored"):
                self.install()
        self.assertEqual(self.dll.read_text(), "original")
        self.assertEqual(tool.load(self.state)["status"], "restored")
        self.assertFalse((self.prefix / tool.OWNER_REL).exists())

    def test_archive_failure_does_not_begin_restore(self):
        self.install()
        installed = self.dll.read_bytes()
        with patch.object(tool, "copy_evidence", side_effect=OSError("archive disk full")):
            with self.assertRaisesRegex(OSError, "archive disk full"):
                self.restore()
        self.assertEqual(self.dll.read_bytes(), installed)
        self.assertTrue((self.prefix / tool.OWNER_REL).exists())
        self.assertEqual(tool.load(self.state)["status"], "restore_failed")
        self.restore()
        self.assertFalse(self.dll.exists())

    def test_unexpected_directory_is_preserved_and_recovery_can_resume(self):
        self.install()
        self.dll.unlink()
        self.dll.mkdir()
        (self.dll / "user-file").write_text("retain")
        with self.assertRaisesRegex(RuntimeError, "directory replaced"):
            self.restore()
        self.assertEqual((self.dll / "user-file").read_text(), "retain")
        self.dll.rename(self.root / "preserved-user-dir")
        self.restore()
        self.assertEqual(tool.load(self.state)["status"], "restored")

    def test_symlink_parent_rejected_before_mutation(self):
        external = self.root / "external"
        external.mkdir()
        (self.prefix / "drive_c/opti2xmx-driver").symlink_to(external)
        with self.assertRaisesRegex(RuntimeError, "Symlink parent"):
            self.install()
        self.assertFalse(self.state.exists())
        self.assertEqual(list(external.iterdir()), [])

    def test_busy_game_refused_before_mutation(self):
        with patch.object(tool, "game_idle", side_effect=RuntimeError("Game is running")):
            with self.assertRaisesRegex(RuntimeError, "Game is running"):
                self.install()
        self.assertFalse(self.state.exists())

    def test_second_install_cannot_replace_active_owner(self):
        self.install()
        self.args.state = str(self.root / "second-state")
        with self.assertRaisesRegex(RuntimeError, "already has"):
            self.install()
        self.assertFalse((self.root / "second-state").exists())

    def test_shell_config_quotes_paths_and_preserves_command_arguments(self):
        self.install()
        config = self.state / "game.conf"
        script = '. "$1"; shift; exec "$@"'
        code = "import os,json,sys; print(json.dumps([os.environ['ANV_CM_HELPER'],sys.argv[1:]]))"
        result = subprocess.run(["bash", "-c", script, "test", str(config), sys.executable, "-c", code,
                                 "argument with spaces", "$(touch BAD2)"], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        helper, args = json.loads(result.stdout)
        self.assertEqual(helper, str(self.package / "tools/cm-compile.sh"))
        self.assertEqual(args, ["argument with spaces", "$(touch BAD2)"])
        self.assertFalse((self.root / "BAD").exists())
        self.assertFalse((self.root / "BAD2").exists())

    def test_alt_directory_and_overrides_are_preserved_across_stock_driverstore_refresh(self):
        stock=self.prefix/'drive_c/windows/system32/DriverStore/FileRepository/igd_faux.inf_1/igdext64.dll'
        stock.parent.mkdir(parents=True);stock.write_bytes(b'stock before')
        self.install()
        stock.write_bytes(b'stock refreshed by Proton')
        script='. "$1"; python3 -c '+__import__('shlex').quote(
            'import json,os; print(json.dumps([os.environ["INTC_ALT_DRIVER_EXTENSIONS_PATH"],os.environ["WINEDLLOVERRIDES"]]))')
        result=subprocess.run(['bash','-c',script,'test',str(self.state/'game.conf')],text=True,capture_output=True,
                              env=dict(os.environ,WINEDLLOVERRIDES='foo,igdext64=b;dxgi=n;IGDEXT64=;bar=b'))
        self.assertEqual(result.returncode,0,result.stderr)
        path,overrides=json.loads(result.stdout)
        self.assertEqual(path,'C:\\opti2xmx-driver')
        self.assertEqual(overrides,'foo=b;dxgi=n;bar=b;igdext64=n,b')
        self.assertEqual(self.dll.read_bytes(),(self.package/'igdext64.dll').read_bytes())
        self.restore()
        self.assertEqual(stock.read_bytes(),b'stock refreshed by Proton')

    def test_legacy_driverstore_journal_restores_its_recorded_path(self):
        legacy=Path('drive_c/windows/system32/driverstore/filerepository/igd_faux.inf_1/igdext64.dll')
        old=self.prefix/legacy;old.parent.mkdir(parents=True);old.write_bytes(b'old original')
        with patch.object(tool,'DLL_REL',legacy):self.install()
        self.assertEqual(tool.recorded_dll_path(tool.load(self.state)),old)
        self.restore()
        self.assertEqual(old.read_bytes(),b'old original')
        self.assertFalse(self.dll.exists())

    def test_real_launcher_missing_compiler_falls_back_before_game_command(self):
        self.install()
        (self.package / "tools/cm-compile.sh").unlink()
        code = "import os,json; print(json.dumps({k:os.environ.get(k) for k in ['IGDEXT_FORCE_FALLBACK','ANV_CM_HELPER','VK_DRIVER_FILES']}))"
        result = subprocess.run([str(self.state / "launch.sh"), sys.executable, "-c", code],
                                capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["IGDEXT_FORCE_FALLBACK"], "1")
        self.assertIsNone(env["ANV_CM_HELPER"])
        self.assertNotIn(str(self.state / "intel_icd.json"), env["VK_DRIVER_FILES"] or "")
        self.assertIn("generic XeSS fallback", (self.state / "launch.log").read_text())
        self.assertIn("Compiler helper is missing", (self.state / "launch.log").read_text())

    def test_root_and_sudo_are_rejected_before_state_or_absent_dll_creation(self):
        with patch.object(tool.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "root/sudo"):
                tool.install(self.args)
        with patch.object(tool.os, "geteuid", return_value=1000), patch.object(tool.os, "getuid", return_value=1000):
            with patch.dict(os.environ, {"SUDO_UID": "1000"}):
                with self.assertRaisesRegex(RuntimeError, "root/sudo"):
                    tool.install(self.args)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.dll.exists())

    def test_foreign_prefix_owner_rejected_even_when_dll_absent(self):
        uid = os.getuid()
        with patch.object(tool.os, "getuid", return_value=uid + 1):
            with self.assertRaisesRegex(RuntimeError, "Output directory must belong"):
                self.install()
        self.assertFalse(self.state.exists())
        self.assertFalse(self.dll.exists())

    def test_foreign_state_and_output_parent_rejected_before_any_mutation(self):
        for name in ("state", "config", "dll"):
            with self.subTest(name=name):
                parent = self.root / ("foreign-" + name)
                parent.mkdir()
                if name == "state":
                    self.args.state = str(parent / "state")
                elif name == "config":
                    self.args.state = str(self.state)
                    self.args.config = str(parent / "game.conf")
                else:
                    self.args.config = None
                    self.dll.parent.mkdir(parents=True)
                    parent = self.dll.parent
                original_stat = Path.stat

                def foreign_stat(path, *args, **kwargs):
                    result = original_stat(path, *args, **kwargs)
                    if path == parent:
                        values = list(result)
                        values[4] = os.getuid() + 1
                        return os.stat_result(values)
                    return result

                with patch.object(Path, "stat", new=foreign_stat):
                    with self.assertRaisesRegex(RuntimeError, "Output directory must belong"):
                        self.install()
                self.assertFalse(self.state.exists())
                self.assertFalse(self.dll.exists())

    def test_recreated_prefix_missing_owner_marker_preserves_new_dll(self):
        self.install()
        (self.prefix / tool.OWNER_REL).unlink()
        self.dll.write_text("fresh prefix DLL must survive")
        with self.assertRaisesRegex(RuntimeError, "ownership marker is missing"):
            self.restore()
        self.assertEqual(self.dll.read_text(), "fresh prefix DLL must survive")
        self.assertEqual(tool.load(self.state)["status"], "active")

    def test_partial_restore_persists_progress_and_retries(self):
        self.dll.parent.mkdir(parents=True)
        self.dll.write_text("original")
        self.install()
        original = tool.restore_file
        failed = False

        def fail_once(record):
            nonlocal failed
            if record["label"] == "game.conf" and not failed:
                failed = True
                raise OSError("temporary restore error")
            return original(record)

        with patch.object(tool, "restore_file", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "temporary restore error"):
                self.restore()
        self.assertEqual(tool.load(self.state)["restore_progress"], ["igdext64.dll"])
        self.assertTrue((self.prefix / tool.OWNER_REL).exists())
        self.restore()
        self.assertEqual(self.dll.read_text(), "original")
        self.assertEqual(tool.load(self.state)["status"], "restored")

    def test_missing_ocloc_and_unloadable_igc_are_detected_without_gpu_probe(self):
        ocloc = self.package / "igc/neo/bin/ocloc"
        ocloc.unlink()
        ok, message = tool.compiler_check(self.package)
        self.assertFalse(ok)
        self.assertIn("ocloc is missing", message)
        ocloc.write_text("fixture")
        ocloc.chmod(0o700)
        (self.package / "igc/igc/local/lib/libigdfcl.so").write_text("invalid shared-library fixture")
        real_run = subprocess.run

        def pass_dependency_listing(command, **kwargs):
            if command[0] in ("ldd", "bash"):
                return subprocess.CompletedProcess(command, 0, "fixture dependency listing", "")
            return real_run(command, **kwargs)

        with patch.object(tool.subprocess, "run", side_effect=pass_dependency_listing):
            ok, message = tool.compiler_check(self.package)
        self.assertFalse(ok)
        self.assertIn("IGC load failed", message)

    def test_retry_after_owner_removal_uses_persisted_progress(self):
        self.dll.parent.mkdir(parents=True)
        self.dll.write_text("original")
        self.install()
        original = tool.restore_file

        def fail_after_owner_removal(record):
            original(record)
            if record["label"] == "owner":
                raise OSError("interrupted after owner removal")

        with patch.object(tool, "restore_file", side_effect=fail_after_owner_removal):
            with self.assertRaisesRegex(OSError, "interrupted after owner removal"):
                self.restore()
        manifest = tool.load(self.state)
        self.assertEqual(manifest["restore_progress"], ["igdext64.dll", "game.conf"])
        self.assertTrue(manifest["owner_cleanup_pending"])
        self.assertFalse((self.prefix / tool.OWNER_REL).exists())
        self.dll.write_text("later file after successful data restoration")
        self.restore()
        self.assertEqual(self.dll.read_text(), "later file after successful data restoration")
        self.assertEqual(tool.load(self.state)["status"], "restored")

    def test_versioned_bundle_library_names_are_supported(self):
        igc = self.package / "igc/igc/local/lib"
        (igc / "libigc.so").rename(igc / "libigc.so.2.10.10")
        (igc / "libigc.so.2").symlink_to("libigc.so.2.10.10")
        (igc / "libigdfcl.so.2.10.10").write_text("fixture")
        (igc / "libigdfcl.so.2").symlink_to("libigdfcl.so.2.10.10")
        commands = []

        def successful_startup(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "fixture startup", "")

        with patch.object(tool.subprocess, "run", side_effect=successful_startup):
            ok, report = tool.compiler_check(self.package)
        self.assertTrue(ok, report)
        self.assertIn(["ldd", str(igc / "libigc.so.2")], commands)
        self.assertIn(["ldd", str(igc / "libigdfcl.so.2")], commands)

    def test_frozen_decky_preflight_uses_host_python_and_clean_environment(self):
        (self.package / 'igc/igc/local/lib/libigdfcl.so.2').write_text('fixture')
        calls = []
        def successful(command, **kwargs):
            calls.append((command, kwargs['env']))
            return subprocess.CompletedProcess(command, 0, 'deviceName = Intel fixture', '')
        with patch.object(tool.sys, 'executable', '/decky/PluginLoader'), \
             patch.object(tool.shutil, 'which', return_value='/usr/bin/python3'), \
             patch.dict(tool.os.environ, {'LD_LIBRARY_PATH': '/decky/lib', 'LD_LIBRARY_PATH_ORIG': '/host/lib',
                                          'PYTHONHOME': '/decky', 'PYTHONPATH': '/decky'}, clear=False), \
             patch.object(tool.subprocess, 'run', side_effect=successful):
            self.assertTrue(tool.driver_check(self.package, self.root / 'fixture.json')[0])
            self.assertTrue(tool.compiler_check(self.package)[0])
        python_calls = [(command, env) for command, env in calls if '-c' in command]
        self.assertEqual(len(python_calls), 3)
        for command, env in python_calls:
            self.assertEqual(command[0], '/usr/bin/python3')
            self.assertNotIn('/decky', env.get('LD_LIBRARY_PATH', ''))
            self.assertNotIn('PYTHONHOME', env); self.assertNotIn('PYTHONPATH', env)

    def test_missing_compiler_never_selects_usable_driver_xmx_path(self):
        self.install()
        (self.package / "igc/neo/bin/ocloc").unlink()
        captured = {}

        def capture_exec(file, argv, env):
            captured.update(file=file, argv=argv, env=env)
            raise SystemExit(0)

        with patch.object(tool, "driver_check", return_value=(True, "deviceName = Intel fixture")) as driver:
            with patch.object(tool.os, "execvpe", side_effect=capture_exec), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tool.launch(argparse.Namespace(state=str(self.state), command=["--", "/bin/true"]))
        driver.assert_not_called()
        self.assertEqual(captured["file"], "/bin/true")
        self.assertEqual(captured["env"]["IGDEXT_FORCE_FALLBACK"], "1")


if __name__ == "__main__":
    unittest.main()
