"""Slot switch regression tests; no real boot selection or reboot requests."""
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'slot-switch' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


boot = load('slot_boot', 'boot.py')
desktop = load('slot_desktop', 'desktop.py')


class FakeBoot:
    def __init__(self, directory):
        self.conf = Path(directory)
        self.current, self.selected, self.operation = 'A', 'A', 'idle'
        self.calls, self.fail, self.ignore, self.conflict = [], False, False, False
        self.write_failure = False
        self.values = {'A': {'boot-requested-at': 20990101000000, 'image-invalid': 0},
                       'B': {'boot-requested-at': 0, 'image-invalid': 0}}
        for slot in ('A', 'B'): (self.conf / (slot + '.conf')).write_text(slot)

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == boot.BUSCTL:
            return 'de.pengutronix.rauc 123 rauc root' if args[-1] == 'list' else 's "' + self.operation + '"'
        if args[0] == boot.SYSTEMCTL:
            if args[1] == 'show': return 'Job=' if 'Job' in args else 'masked' if 'UnitFileState' in args else 'inactive'
            if self.conflict: (self.conf / 'B.conf').write_text('external writer')
            if self.fail or self.conflict: raise RuntimeError('reboot refused')
            return ''
        if args[1] == 'this-image': return self.current
        if args[1] == 'selected-image': return self.selected
        slot = args[args.index('--image') + 1]
        if '--get' in args:
            key = args[-1]; return key + ': ' + str(self.values[slot].get(key, 0))
        if self.write_failure:
            (self.conf / (slot + '.conf')).write_text('uncertain write')
            raise RuntimeError('write failed')
        if not self.ignore:
            (self.conf / (slot + '.conf')).write_text('selected ' + slot)
            self.selected = slot
        return ''


class FakeUpdater:
    """Service transitions, including commands which mutate before failing."""
    def __init__(self, fallback=None):
        self.fallback = fallback
        self.calls = []
        self.states = {'atomupd.service': 'active', 'rauc.service': 'inactive'}
        self.masks = {}
        self.jobs = {}
        self.operation = 'idle'
        self.after_mask = None
        self.stop_error = False
        self.stop_ignored = False
        self.start_error = False

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == boot.BUSCTL:
            if args[-1] == 'list':
                return 'de.pengutronix.rauc 123 rauc root' if self.states['rauc.service'] == 'active' or self.operation != 'idle' else ''
            return 's "' + self.operation + '"'
        if args[0] == boot.SYSTEMCTL and args[1] != 'reboot':
            action, service = args[1], args[2] if args[1] == 'show' else args[-1]
            if action == 'show':
                if 'Job' in args: return 'Job=' + self.jobs.get(service, '')
                return self.masks.get(service, 'disabled') if 'UnitFileState' in args else self.states[service]
            if action == 'mask':
                self.masks[service] = 'masked-runtime'
                if self.after_mask: self.after_mask(service)
            elif action == 'unmask': self.masks.pop(service, None)
            elif action == 'stop':
                if not self.stop_ignored: self.states[service] = 'inactive'
                if self.stop_error: raise RuntimeError('stop failed after taking effect')
            elif action == 'start':
                if self.start_error: raise RuntimeError('start refused')
                self.states[service] = 'active'
            return ''
        return self.fallback(args) if self.fallback else ''


class SwitchChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.fw = FakeBoot(self.temp.name)
        self.controller = boot.Controller(self.fw, self.temp.name, Path(self.temp.name) / 'records')
        self.original = {s: (self.fw.conf / (s + '.conf')).read_bytes() for s in ('A', 'B')}
        # Native Windows cannot model root-owned Unix paths. Use actual file
        # contents for state/rollback tests; Linux-only tests cover path guards.
        def read(path, maximum=65536): return Path(path).read_bytes(), 0o600
        self.patches = [patch.object(boot, 'preflight'), patch.object(boot, 'read_file', side_effect=read),
                        patch.object(boot, 'reboot_lock', return_value=nullcontext()),
                        patch.object(boot.Path, 'read_text', autospec=True, side_effect=lambda path, *a, **k: 'ID=steamos\nVERSION_ID=3.10\n' if path.as_posix() == '/etc/os-release' else path.read_bytes().decode())]
        if os.name == 'nt':
            def restore(path, original, expected):
                if read(path) != expected: raise RuntimeError('Concurrent write')
                path.write_bytes(original[0])
            self.patches.append(patch.object(boot, 'restore_file', side_effect=restore))
        for guard in self.patches: guard.start(); self.addCleanup(guard.stop)

    def test_status_is_read_only(self):
        state = self.controller.status()
        self.assertEqual((state['current'], state['target']), ('A', 'B'))
        self.assertFalse(any('--set' in call or call == [boot.SYSTEMCTL, 'reboot'] for call in self.fw.calls))

    def test_future_timestamp_and_both_directions(self):
        for current, target in [('A', 'B'), ('B', 'A')]:
            self.fw.current = self.fw.selected = current
            state = self.controller.status(); result = self.controller.reboot(target, state['token'])
            self.assertEqual(result['target'], target)
            write = next(call for call in reversed(self.fw.calls) if '--set' in call)
            self.assertGreater(int(write[write.index('boot-requested-at') + 1]), 20990101000000)
            self.assertEqual((self.fw.conf / (current + '.conf')).read_bytes(), self.original[current] if current == 'A' else b'selected B')

    def test_busy_invalid_and_unrecognized_current_refuse_writes(self):
        for kind in ('busy', 'invalid', 'unknown'):
            with self.subTest(kind=kind):
                self.fw.operation = 'installing' if kind == 'busy' else 'idle'
                self.fw.values['B']['image-invalid'] = 1 if kind == 'invalid' else 0
                self.fw.current = '?' if kind == 'unknown' else 'A'
                with self.assertRaises(RuntimeError): self.controller.status()
                self.assertFalse(any('--set' in call for call in self.fw.calls))

    def test_stale_confirmation_refuses_write(self):
        state = self.controller.status(); (self.fw.conf / 'B.conf').write_text('updated')
        with self.assertRaisesRegex(RuntimeError, 'state changed'): self.controller.reboot('B', state['token'])
        self.assertFalse(any('--set' in call for call in self.fw.calls))

    def test_reboot_failure_restores_target(self):
        state = self.controller.status(); self.fw.fail = True
        with self.assertRaisesRegex(RuntimeError, 'selection restored'): self.controller.reboot('B', state['token'])
        for slot in ('A', 'B'): self.assertEqual((self.fw.conf / (slot + '.conf')).read_bytes(), self.original[slot])

    def test_readback_failure_does_not_reboot(self):
        state = self.controller.status(); self.fw.ignore = True
        with self.assertRaisesRegex(RuntimeError, 'verification failed'): self.controller.reboot('B', state['token'])
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], self.fw.calls)

    def test_concurrent_writer_preserved_on_reboot_failure(self):
        state = self.controller.status(); self.fw.conflict = True
        with self.assertRaisesRegex(RuntimeError, 'restoration also failed'): self.controller.reboot('B', state['token'])
        self.assertEqual((self.fw.conf / 'B.conf').read_text(), 'external writer')

    def test_invalid_arguments_refused(self):
        for target, token in [('C', 'a' * 64), ('A; reboot', 'a' * 64), ('B', 'invalid')]:
            with self.assertRaises(ValueError): self.controller.reboot(target, token)
        self.assertFalse(self.fw.calls)

    def test_failed_write_does_not_overwrite_unknown_result(self):
        state = self.controller.status(); self.fw.write_failure = True
        with self.assertRaisesRegex(RuntimeError, 'restoration also failed'): self.controller.reboot('B', state['token'])
        self.assertEqual((self.fw.conf / 'B.conf').read_text(), 'uncertain write')
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], self.fw.calls)

    def test_running_updater_is_never_stopped(self):
        def active(args):
            self.fw.calls.append(args)
            return 'Job=' if 'Job' in args else 'active'
        with self.assertRaisesRegex(RuntimeError, 'RAUC is running'):
            boot.Controller(active).reboot('B', 'a' * 64)
        self.assertFalse(any('--set' in call or 'stop' in call for call in self.fw.calls))

    def test_temporary_masks_retained_until_successful_reboot(self):
        calls, masked = [], set()
        def run(args):
            calls.append(args)
            if args[0] == boot.BUSCTL: return ''
            if args[1] == 'show': return 'Job=' if 'Job' in args else ('masked-runtime' if args[2] in masked else 'disabled') if 'UnitFileState' in args else 'inactive'
            if args[1] == 'mask': masked.add(args[-1])
            elif args[1] == 'unmask': masked.remove(args[-1])
            return ''
        with boot.Controller(run).update_guard() as guard: guard['reboot_requested'] = True
        self.assertEqual(masked, {'atomupd.service', 'rauc.service'})
        self.assertFalse(any('unmask' in args for args in calls))

    def test_mask_cleanup_attempts_every_service_after_one_failure(self):
        calls, masked = [], set()
        def run(args):
            calls.append(args)
            if args[0] == boot.BUSCTL: return ''
            if args[1] == 'show': return 'Job=' if 'Job' in args else ('masked-runtime' if args[2] in masked else 'disabled') if 'UnitFileState' in args else 'inactive'
            if args[1] == 'mask': masked.add(args[-1])
            elif args[1] == 'unmask':
                if args[-1] == 'rauc.service': raise RuntimeError('cleanup failed')
                masked.remove(args[-1])
            return ''
        with self.assertRaisesRegex(RuntimeError, 'Could not restore temporary updater masks'):
            with boot.Controller(run).update_guard(): raise RuntimeError('cancelled')
        self.assertIn([boot.SYSTEMCTL, 'unmask', '--runtime', 'atomupd.service'], calls)
        self.assertEqual(masked, {'rauc.service'})

    def test_paused_rauc_is_not_activated(self):
        def inactive(args):
            if args[0] == boot.BUSCTL: return 'de.pengutronix.rauc - - - (activatable)'
            return 'inactive'
        boot.Controller(inactive).idle()

    def test_running_atomupd_status_is_read_only_and_default_refuses(self):
        updater = FakeUpdater(self.fw)
        controller = boot.Controller(updater, self.temp.name, Path(self.temp.name) / 'records')
        state = controller.status()
        self.assertFalse(any(call[1] in ('stop', 'mask', 'unmask', 'start') for call in updater.calls))
        with self.assertRaisesRegex(RuntimeError, 'Explicitly choose'):
            controller.reboot('B', state['token'])
        self.assertFalse(any('stop' in call or '--set' in call for call in updater.calls))

    def test_explicit_stop_masks_first_and_reboots_without_restoring(self):
        updater = FakeUpdater(self.fw)
        controller = boot.Controller(updater, self.temp.name, Path(self.temp.name) / 'records')
        state = controller.status()
        controller.reboot('B', state['token'], stop_updaters=True)
        stop = updater.calls.index([boot.SYSTEMCTL, 'stop', 'atomupd.service'])
        for service in updater.states:
            self.assertLess(updater.calls.index([boot.SYSTEMCTL, 'mask', '--runtime', service]), stop)
        self.assertNotIn([boot.SYSTEMCTL, 'stop', 'rauc.service'], updater.calls)
        self.assertFalse(any(call[1] in ('unmask', 'start') for call in updater.calls))
        self.assertEqual(updater.states['atomupd.service'], 'inactive')
        self.assertEqual(set(updater.masks), set(updater.states))

    def test_busy_unknown_or_active_idle_rauc_never_stopped(self):
        for operation in ('idle', 'installing', 'unknown'):
            for state in ('active', 'activating'):
                with self.subTest(operation=operation, state=state):
                    updater = FakeUpdater(); updater.operation = operation
                    updater.states['rauc.service'] = state
                    with self.assertRaises(RuntimeError):
                        with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
                    self.assertFalse(any(call[1] in ('stop', 'mask') for call in updater.calls))

    def test_unknown_rauc_operation_with_inactive_unit_refuses_stop(self):
        updater = FakeUpdater(); updater.operation = 'unknown'
        with self.assertRaisesRegex(RuntimeError, 'system update is running'):
            with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
        self.assertFalse(any(call[1] == 'stop' for call in updater.calls))

    def test_rauc_activation_race_during_masking_refuses_before_stop(self):
        updater = FakeUpdater()
        updater.after_mask = lambda service: updater.states.update({'rauc.service': 'active'})
        with self.assertRaisesRegex(RuntimeError, 'RAUC is running'):
            with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
        self.assertFalse(any(call[1] == 'stop' for call in updater.calls))
        self.assertEqual(updater.masks, {})
        self.assertEqual(updater.states['atomupd.service'], 'active')

    def test_queued_job_after_masks_refuses_before_stopping(self):
        for service in ('atomupd.service', 'rauc.service'):
            with self.subTest(service=service):
                updater = FakeUpdater()
                updater.after_mask = lambda masked: updater.jobs.update({service: '123'})
                with self.assertRaisesRegex(RuntimeError, 'queued job'):
                    with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
                self.assertFalse(any(call[1] == 'stop' for call in updater.calls))
                self.assertEqual(updater.masks, {})

    def test_unknown_job_property_refuses_before_stopping(self):
        updater = FakeUpdater()
        def run(args):
            return '' if 'Job' in args else updater(args)
        with self.assertRaisesRegex(RuntimeError, 'unknown job state'):
            with boot.Controller(run).update_guard(stop_updaters=True): self.fail('must refuse')
        self.assertFalse(any(call[1] == 'stop' for call in updater.calls))
        self.assertEqual(updater.masks, {})

    def test_stop_partial_failure_restores_service_and_masks(self):
        updater = FakeUpdater(); updater.stop_error = True
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
        self.assertEqual(updater.states['atomupd.service'], 'active')
        self.assertEqual(updater.masks, {})
        self.assertIn([boot.SYSTEMCTL, 'start', 'atomupd.service'], updater.calls)

    def test_stop_ignored_refuses_and_does_not_restart_running_service(self):
        updater = FakeUpdater(); updater.stop_ignored = True
        with self.assertRaisesRegex(RuntimeError, 'started concurrently'):
            with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
        self.assertEqual(updater.masks, {})
        self.assertNotIn([boot.SYSTEMCTL, 'start', 'atomupd.service'], updater.calls)

    def test_cancel_restores_previous_running_service_and_preserves_existing_mask(self):
        updater = FakeUpdater(); updater.masks['rauc.service'] = 'masked'
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            with boot.Controller(updater).update_guard(stop_updaters=True): raise RuntimeError('cancelled')
        self.assertEqual(updater.states['atomupd.service'], 'active')
        self.assertEqual(updater.masks, {'rauc.service': 'masked'})
        self.assertNotIn([boot.SYSTEMCTL, 'unmask', '--runtime', 'rauc.service'], updater.calls)

    def test_preexisting_masked_running_updater_refuses_without_stopping(self):
        for mask in ('masked', 'masked-runtime'):
            updater = FakeUpdater(); updater.masks['atomupd.service'] = mask
            with self.assertRaisesRegex(RuntimeError, 'already masked'):
                with boot.Controller(updater).update_guard(stop_updaters=True): self.fail('must refuse')
            self.assertEqual(updater.masks, {'atomupd.service': mask})
            self.assertFalse(any(call[1] in ('stop', 'unmask') for call in updater.calls))

    def test_reboot_failure_restores_updater_and_target_configuration(self):
        updater = FakeUpdater(self.fw); self.fw.fail = True
        controller = boot.Controller(updater, self.temp.name, Path(self.temp.name) / 'records')
        state = controller.status()
        with self.assertRaisesRegex(RuntimeError, 'selection restored'):
            controller.reboot('B', state['token'], stop_updaters=True)
        self.assertEqual(updater.states['atomupd.service'], 'active')
        self.assertEqual(updater.masks, {})
        for slot in ('A', 'B'): self.assertEqual((self.fw.conf / (slot + '.conf')).read_bytes(), self.original[slot])

    def test_restart_failure_is_reported_after_mask_cleanup(self):
        updater = FakeUpdater(); updater.start_error = True
        with self.assertRaisesRegex(RuntimeError, 'atomupd.service restart: start refused'):
            with boot.Controller(updater).update_guard(stop_updaters=True): raise RuntimeError('cancelled')
        self.assertEqual(updater.masks, {})

    def test_cli_stop_flag_requires_explicit_reboot_request(self):
        with patch.object(boot, 'Controller') as controller, patch('builtins.print'), \
             patch('sys.argv', ['boot.py', 'reboot', 'B', 'a' * 64, '--stop-updaters']):
            controller.return_value.reboot.return_value = {}
            self.assertEqual(boot.main(), 0)
            controller.return_value.reboot.assert_called_once_with('B', 'a' * 64, stop_updaters=True)
        with patch.object(boot, 'Controller') as controller, patch('builtins.print'), \
             patch('sys.argv', ['boot.py', 'status', '--stop-updaters']):
            self.assertEqual(boot.main(), 1)
            controller.assert_not_called()


class DesktopChecks(unittest.TestCase):
    def state(self):
        return {'current': 'A', 'selected': 'A', 'target': 'B', 'token': 'a' * 64,
                'installation_records': {'B': {'version': '<b>unsafe</b>', 'system': '3.10', 'build': 'test'}}}

    def helper_result(self, reply, code=0):
        return SimpleNamespace(returncode=code, stdout=json.dumps(reply), stderr='')

    def test_helper_keeps_pkexec_interactive_authentication_available(self):
        # The same invocation works with polkit rules or its normal interactive
        # authorization flow; do not disable the internal authentication agent.
        state = self.state()
        with patch.object(desktop.subprocess, 'run', return_value=self.helper_result({'ok': True, 'data': state})) as run:
            self.assertEqual(desktop.helper('status'), state)
            run.assert_called_once_with(['/usr/bin/pkexec', desktop.HELPER, 'status'], text=True,
                                        stdout=desktop.subprocess.PIPE, stderr=desktop.subprocess.PIPE)

    def test_helper_reports_authorization_exit_codes_without_password_accusation(self):
        for zh in (False, True):
            for code, expected in ((126, '授权已取消' if zh else 'Authorization was cancelled'),
                                   (127, '未能获得授权或启动后台程序' if zh else 'Could not obtain authorization or start the helper')):
                for stdout in ('', 'not JSON', 'null', '[]'):
                    with self.subTest(zh=zh, code=code, stdout=stdout), patch.object(desktop, 'ZH', zh), \
                         patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(
                             returncode=code, stdout=stdout, stderr='SECRET_TOKEN=do-not-display')):
                        with self.assertRaisesRegex(RuntimeError, expected) as raised:
                            desktop.helper('status')
                        self.assertNotIn('密码', str(raised.exception))
                        self.assertNotIn('password', str(raised.exception).lower())
                        self.assertNotIn('SECRET_TOKEN', str(raised.exception))

    def test_helper_missing_pkexec_has_distinct_error(self):
        with patch.object(desktop, 'ZH', False), patch.object(desktop.subprocess, 'run', side_effect=FileNotFoundError('secret path')):
            with self.assertRaisesRegex(RuntimeError, 'Could not start pkexec') as raised:
                desktop.helper('status')
            self.assertNotIn('secret path', str(raised.exception))

    def test_helper_backend_failure_and_invalid_output_are_not_authorization_errors(self):
        with patch.object(desktop, 'ZH', False):
            for code in (0, 1, 2):
                with self.subTest(code=code), patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=code, stdout='SECRET_TOKEN=do-not-display', stderr='SECRET_TOKEN=do-not-display')):
                    with self.assertRaisesRegex(RuntimeError, 'valid response.*exit status ' + str(code)) as raised:
                        desktop.helper('status')
                    self.assertNotIn('SECRET_TOKEN', str(raised.exception))
                    self.assertNotIn('password', str(raised.exception).lower())
            with patch.object(desktop.subprocess, 'run', return_value=self.helper_result(
                    {'ok': False, 'error': 'RAUC is running; switching refused.'}, 1)):
                with self.assertRaisesRegex(RuntimeError, 'RAUC is running; switching refused'):
                    desktop.helper('status')

    def test_helper_rejects_malformed_envelopes_and_success_exit_mismatch(self):
        for reply in (None, [], 'text', {}, {'ok': 1, 'data': self.state()},
                      {'ok': False}, {'ok': False, 'error': 1}, {'ok': False, 'error': ' '},
                      {'ok': True}, {'ok': True, 'data': []}):
            with self.subTest(reply=reply), patch.object(desktop, 'ZH', False), \
                 patch.object(desktop.subprocess, 'run', return_value=self.helper_result(reply)):
                with self.assertRaisesRegex(RuntimeError, 'valid response'): desktop.helper('status')
        with patch.object(desktop, 'ZH', False), patch.object(desktop.subprocess, 'run', return_value=self.helper_result(
                {'ok': True, 'data': self.state()}, 1)):
            with self.assertRaisesRegex(RuntimeError, 'valid response'): desktop.helper('status')

    def test_helper_validates_status_before_showing_confirmation(self):
        for key, value in (('current', None), ('selected', 'C'), ('target', 'A'), ('token', 'bad'),
                           ('current_system', []), ('installation_records', []),
                           ('installation_records', {'B': []}),
                           ('installation_records', {'B': {'version': {'bad': 'metadata'}}})):
            state = self.state(); state[key] = value
            with self.subTest(key=key, value=value), patch.object(desktop, 'ZH', False), \
                 patch.object(desktop.subprocess, 'run', return_value=self.helper_result({'ok': True, 'data': state})):
                with self.assertRaisesRegex(RuntimeError, 'valid response'): desktop.helper('status')

    def test_helper_validates_reboot_acknowledgement(self):
        for data in ({}, {'reboot_requested': True, 'target': 'A'}, {'reboot_requested': 1, 'target': 'B'}):
            with self.subTest(data=data), patch.object(desktop, 'ZH', False), \
                 patch.object(desktop.subprocess, 'run', return_value=self.helper_result({'ok': True, 'data': data})):
                with self.assertRaisesRegex(RuntimeError, 'valid response'): desktop.helper('reboot', 'B', 'a' * 64)
        data = {'reboot_requested': True, 'target': 'B'}
        with patch.object(desktop.subprocess, 'run', return_value=self.helper_result({'ok': True, 'data': data})):
            self.assertEqual(desktop.helper('reboot', 'B', 'a' * 64), data)

    def test_cancel_never_changes_selection(self):
        with patch.object(desktop, 'helper', return_value=self.state()) as helper, \
             patch.object(desktop.subprocess, 'run') as run:
            run.return_value.returncode = 1
            self.assertEqual(desktop.main(), 0)
            helper.assert_called_once_with('status')

    def test_confirm_uses_reviewed_target_and_token(self):
        state = self.state()
        with patch.object(desktop, 'helper', side_effect=[state, {}]) as helper, \
             patch.object(desktop.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            self.assertEqual(desktop.main(), 0)
            self.assertEqual(helper.call_args_list[1].args, ('reboot', 'B', state['token']))

    def test_updater_option_is_unchecked_and_explicit_choice_sets_flag(self):
        state = self.state()
        with patch.object(desktop, 'helper', side_effect=[state, {}]) as helper, \
             patch.object(desktop.subprocess, 'run', side_effect=[
                 SimpleNamespace(returncode=0, stdout='"stop-updaters"\n'), SimpleNamespace(returncode=0)]) as run:
            self.assertEqual(desktop.main(), 0)
            self.assertEqual(run.call_args_list[0].args[0][-1], 'off')
            self.assertIn('--checklist', run.call_args_list[0].args[0])
            self.assertEqual(helper.call_args_list[1].args, ('reboot', 'B', state['token'], '--stop-updaters'))
            self.assertIn('RAUC', run.call_args_list[1].args[0][-1])

    def test_final_confirmation_cancel_after_opt_in_never_requests_reboot(self):
        with patch.object(desktop, 'helper', return_value=self.state()) as helper, \
             patch.object(desktop.subprocess, 'run', side_effect=[
                 SimpleNamespace(returncode=0, stdout='stop-updaters'), SimpleNamespace(returncode=1)]):
            self.assertEqual(desktop.main(), 0)
            helper.assert_called_once_with('status')

    def test_bilingual_copy_and_metadata_escaping(self):
        for zh in (False, True):
            with patch.object(desktop, 'ZH', zh):
                value = desktop.message(self.state())
                self.assertNotIn('<b>unsafe</b>', value)
                self.assertIn('&lt;b&gt;unsafe&lt;/b&gt;', value)
                self.assertIn('安装时记录' if zh else 'installation record', value)
                self.assertIn('存档' if zh else 'saves', value)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Linux root ownership checks')
class PathChecks(unittest.TestCase):
    def test_absolute_image_tool_link_uses_image_namespace(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/bin').mkdir(parents=True)
            target=root/'usr/bin/holo-bootconf'; target.write_text('trusted image tool')
            link=root/'usr/bin/steamos-bootconf'; link.symlink_to('/usr/bin/holo-bootconf')
            self.assertTrue(image_tool(root,'steamos-bootconf'))
            link.unlink(); link.symlink_to('holo-bootconf')
            self.assertTrue(image_tool(root,'steamos-bootconf'))

    def test_host_file_cannot_satisfy_missing_image_dependency(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/bin').mkdir(parents=True)
            (root/'usr/bin/steamos-bootconf').symlink_to('/etc/passwd')
            self.assertFalse(image_tool(root,'steamos-bootconf'))

    def test_writable_image_link_target_and_cycles_are_refused(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/bin').mkdir(parents=True)
            target=root/'usr/bin/holo-bootconf'; target.write_text('untrusted'); target.chmod(0o666)
            link=root/'usr/bin/steamos-bootconf'; link.symlink_to('/usr/bin/holo-bootconf')
            with self.assertRaises(RuntimeError): image_tool(root,'steamos-bootconf')
            target.unlink(); target.symlink_to('steamos-bootconf')
            with self.assertRaisesRegex(RuntimeError,'cycle'): image_tool(root,'steamos-bootconf')

    def test_image_tool_symlink_ancestors_are_resolved_inside_image(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/actual-bin').mkdir(parents=True)
            (root/'usr/bin').symlink_to('/usr/actual-bin',target_is_directory=True)
            target=root/'usr/actual-bin/steamos-bootconf'; target.write_text('trusted')
            self.assertTrue(image_tool(root,'steamos-bootconf'))
            target.unlink(); target.mkdir()
            with self.assertRaises(RuntimeError): image_tool(root,'steamos-bootconf')

    def test_link_and_writable_boot_metadata_refused(self):
        # /tmp is intentionally writable: use a trusted /run parent.
        with tempfile.TemporaryDirectory(dir='/run') as directory:
            path = Path(directory) / 'A.conf'; path.write_text('boot data'); path.chmod(0o600)
            self.assertEqual(boot.read_file(path)[0], b'boot data')
            path.chmod(0o666)
            with self.assertRaises(RuntimeError): boot.read_file(path)
            path.unlink(); path.symlink_to('/etc/passwd')
            with self.assertRaises(OSError): boot.read_file(path)


if __name__ == '__main__': unittest.main()
