from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import operations as op
from oxp3_maintenance.components import build_plan


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.payload, self.root = self.base / 'payload', self.base / 'root'
        self.root.mkdir()
        self.catalog = {'schema': 1, 'repairs': [], 'plugins': []}
        self.manifest = {}
        self.system = {'slot': {'id': 'current', 'label': 'A'}, 'os': dict(op.probe.BASE),
                       'kernel': op.probe.KERNEL, 'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'},
                       'packages': {}, 'bios': '5.09', 'uid': 1000, 'gid': 1000}
        self.prior = []
        self.managed = {'paths': {}, 'components': {}}
        self.adoption_errors = {}
        self.write(self.root, 'usr/share/applications/org.kde.plasma.keyboard.desktop', b'desktop')

    def write(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def component(self, name, dependencies=(), *, available=True, missing=False):
        self.catalog['repairs'].append({'id': name, 'dependencies': list(dependencies), 'available': available})
        source = name + '/file'
        self.write(self.payload, 'integration/' + source, b'payload')
        self.manifest[name] = {'files': [{'source': source, 'target': 'etc/test/' + name}], 'units': [], 'packages': {}}
        if missing:
            self.manifest[name]['missing'] = ['Prepared native resource is unavailable']

    def prepare(self, selected, *, tool_only=False, selected_only=False):
        self.write(self.payload, 'components/options.json', json.dumps(self.catalog).encode())
        self.write(self.payload, 'integration/manifest.json', json.dumps(self.manifest).encode())
        store = mock.Mock()
        store.managed.return_value = copy.deepcopy(self.managed)
        package_store = mock.Mock()
        package_store._read.return_value = None
        def adoption(root, system, names):
            for name in names:
                if name in self.adoption_errors:
                    raise RuntimeError(self.adoption_errors[name])
            return {}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(op, 'current_selection', return_value=self.prior))
            stack.enter_context(mock.patch.object(op, 'PackageStore', return_value=package_store))
            stack.enter_context(mock.patch.object(op.probe, 'verify_shared', return_value=True))
            stack.enter_context(mock.patch.object(op.probe, 'verify_shared_os', return_value=True))
            stack.enter_context(mock.patch.object(op.adoption, 'import_originals', side_effect=adoption))
            stack.enter_context(mock.patch.object(op, 'build_plan', side_effect=lambda payload, root, selected, system, managed: build_plan(payload, self.root, selected, system, managed)))
            return op.prepare(self.payload, selected, copy.deepcopy(self.system), store,
                              tool_only=tool_only, selected_only=selected_only)

    def test_old_native_manual_and_retired_components_do_not_block_portable_choice(self):
        self.component('input')
        self.component('keyboard')
        self.component('slot-switch')
        self.prior = ['input', 'slot-switch', 'retired-fix']
        self.system.update(kernel='new-kernel')
        self.system['os'].update(VERSION_ID='3.11', BUILD_ID='new')
        plan, originals = self.prepare(['keyboard'])
        self.assertEqual(plan['selected'], ['keyboard'])
        self.assertEqual(set(plan['retained']), set(self.prior))
        self.assertEqual(plan['components']['keyboard']['status'], 'ready')
        self.assertEqual(set(plan['files']), {'home/deck/.config/kwinrc'})
        self.assertEqual(originals, {})

    def test_unavailable_and_missing_payload_prior_components_are_retained(self):
        self.component('input', available=False)
        self.component('manager', missing=True)
        self.component('keyboard')
        self.prior = ['input', 'manager']
        plan, _ = self.prepare(['keyboard'])
        self.assertEqual(set(plan['retained']), {'input', 'manager'})
        self.assertEqual(plan['selected'], ['keyboard'])
        self.assertEqual(plan['components']['keyboard']['status'], 'ready')

    def test_invalid_prior_journal_is_retained_without_aborting_catalog(self):
        self.component('input')
        self.component('keyboard')
        self.prior = ['input']
        self.adoption_errors['input'] = 'Original legacy backup is missing'
        plan, _ = self.prepare(['keyboard'])
        self.assertIn('Original legacy backup is missing', plan['retained']['input'])
        self.assertEqual(plan['selected'], ['keyboard'])
        self.assertEqual(plan['components']['keyboard']['status'], 'ready')

    def test_explicit_journal_failure_blocks_only_it_and_its_dependents(self):
        self.component('input')
        self.component('gyro', dependencies=['input'])
        self.component('keyboard')
        self.adoption_errors['input'] = 'Unsafe legacy journal'
        plan, _ = self.prepare(['gyro', 'keyboard'])
        self.assertEqual(plan['components']['input']['status'], 'blocked')
        self.assertIn('Unsafe legacy journal', plan['components']['input']['reason'])
        self.assertEqual(plan['components']['gyro']['status'], 'blocked')
        self.assertEqual(plan['components']['keyboard']['status'], 'ready')
        self.assertEqual(set(plan['files']), {'home/deck/.config/kwinrc'})

    def test_manual_or_missing_explicit_choice_returns_actionable_report(self):
        self.component('keyboard')
        for name in ('slot-switch', 'refind', 'shared-storage', 'retired-fix'):
            with self.subTest(name=name):
                plan, _ = self.prepare([name, 'keyboard'])
                self.assertEqual(plan['components'][name]['status'], 'blocked')
                self.assertEqual(plan['components']['keyboard']['status'], 'ready')

    def test_failed_automatic_root_does_not_install_unused_dependencies(self):
        self.component('manager')
        self.component('native-tdp', dependencies=['manager'], missing=True)
        self.component('keyboard')
        self.prior = ['native-tdp']
        plan, _ = self.prepare(['keyboard'])
        self.assertEqual(plan['selected'], ['keyboard'])
        self.assertNotIn('etc/test/manager', plan['files'])
        self.assertIn('native-tdp', plan['retained'])

    def test_explicit_missing_dependency_isolated_from_other_choices(self):
        self.component('native-tdp', dependencies=['not-in-catalog'])
        self.component('keyboard')
        plan, _ = self.prepare(['native-tdp', 'keyboard'])
        self.assertEqual(plan['components']['native-tdp']['status'], 'blocked')
        self.assertIn('not-in-catalog', plan['components']['native-tdp']['reason'])
        self.assertEqual(plan['components']['keyboard']['status'], 'ready')

    def test_tool_only_never_materializes_or_adopts_components(self):
        self.prior = ['input', 'slot-switch', 'future-adapter']
        self.adoption_errors['input'] = 'must not be read'
        plan, originals = self.prepare(['future-adapter'], tool_only=True)
        self.assertEqual(plan['selected'], [])
        self.assertEqual(plan['components'], {})
        self.assertEqual(plan['files'], {})
        self.assertEqual(set(plan['retained']), set(self.prior))
        self.assertEqual(originals, {})

    def test_selected_only_keyboard_retains_prior_native_components_without_refreshing(self):
        self.component('input')
        self.component('xe-dsb')
        self.component('keyboard')
        self.prior = ['input', 'xe-dsb']
        # Exact-baseline eligibility must not implicitly include these repairs.
        self.adoption_errors.update(input='must not be adopted', **{'xe-dsb': 'must not be adopted'})
        old_input = self.write(self.root, 'etc/test/input', b'installed input')
        old_display = self.write(self.root, 'etc/test/xe-dsb', b'installed display fix')
        plan, originals = self.prepare(['keyboard'], selected_only=True)
        self.assertEqual(plan['selected'], ['keyboard'])
        self.assertEqual(set(plan['components']), {'keyboard'})
        self.assertEqual(plan['components']['keyboard']['status'], 'ready')
        self.assertEqual(set(plan['files']), {'home/deck/.config/kwinrc'})
        self.assertEqual(plan['retained'], {
            'input': 'Kept unchanged; outside the selected update scope',
            'xe-dsb': 'Kept unchanged; outside the selected update scope'})
        self.assertEqual(originals, {})
        self.assertEqual(old_input.read_bytes(), b'installed input')
        self.assertEqual(old_display.read_bytes(), b'installed display fix')

    def test_selected_only_includes_required_dependency_and_removes_it_from_retained(self):
        self.component('input')
        self.component('xe-dsb')
        self.component('keyboard')
        self.component('manager')
        self.component('native-tdp', dependencies=['manager'])
        self.prior = ['input', 'xe-dsb', 'manager']
        self.adoption_errors.update(input='must not be adopted', **{'xe-dsb': 'must not be adopted'})
        plan, _ = self.prepare(['keyboard', 'native-tdp'], selected_only=True)
        self.assertEqual(plan['selected'], ['keyboard', 'manager', 'native-tdp'])
        self.assertEqual(set(plan['components']), {'keyboard', 'manager', 'native-tdp'})
        self.assertTrue(all(item['status'] == 'ready' for item in plan['components'].values()))
        self.assertEqual(set(plan['retained']), {'input', 'xe-dsb'})
        self.assertNotIn('manager', plan['retained'])
        self.assertEqual(set(plan['files']), {'home/deck/.config/kwinrc', 'etc/test/manager', 'etc/test/native-tdp'})

    def test_runtime_preserves_retained_dependencies_and_units(self):
        app = self.base / 'app'
        self.write(app, 'entry.py', b'pass')
        self.write(app, 'OXP3-Maintenance.desktop', b'[Desktop Entry]')
        runtime = self.base / 'runtime'
        old = {'status': 'ready', 'dependencies': ['input'], 'units': ['gyro.service'],
               'compatibility': {'requirements': {'packages': {'inputplumber': 'old-reviewed'}}}}
        self.write(runtime, 'activation.json', json.dumps({'schema': 1, 'components': {'gyro': old}}).encode())
        refreshed = {'status': 'ready', 'dependencies': [], 'units': []}
        with mock.patch.object(op, 'RUNTIME', runtime), mock.patch.object(op.adoption, '_trusted'):
            files = op.runtime_files(app, {'version': '0.2.0'}, {'components': {'keyboard': refreshed}, 'retained': {'gyro': 'unchanged'}})
        activation = json.loads(files['usr/local/lib/oxp3-maintenance/activation.json']['data'])
        self.assertEqual({key: activation['components']['gyro'][key] for key in old}, old)
        self.assertEqual({key: activation['components']['keyboard'][key] for key in refreshed}, refreshed)
        self.assertEqual(activation['components']['keyboard']['installed_project_version'], '0.2.0')

    def test_same_version_apply_allowed_but_downgrade_and_equal_update_refused(self):
        op.check_release_version({'version': '0.2.0'}, {'version': '0.2.0'})
        op.check_release_version({'version': '0.2.1'}, {'version': '0.2.0'}, updating=True)
        for candidate, current, updating in [('0.1.0', '0.2.0', False), ('0.2.0', '0.2.0', True),
                                               ('0.2.0-beta.1', '0.2.0', False)]:
            with self.subTest(candidate=candidate), self.assertRaises(RuntimeError):
                op.check_release_version({'version': candidate}, {'version': current}, updating=updating)


if __name__ == '__main__':
    unittest.main()
