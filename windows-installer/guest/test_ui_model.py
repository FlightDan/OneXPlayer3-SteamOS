import copy
import unittest
from test_handoff import fixture
from install_session import prepare_intent, review
from ui_model import InstallerModel


class Backend:
    available = True; reason = ''
    def __init__(self):
        choice, self.snapshot = fixture(); choice['source'] = {'version': '3.8.14', 'build': '20260707.10'}
        self.choice = choice; self.record = None; self.reads = 0
    def current(self): self.reads += 1; return copy.deepcopy(self.snapshot)
    def refresh(self): return self.current()
    def intent(self): return self.record


class InstallerUiChecks(unittest.TestCase):
    def test_review_does_not_execute_and_back_clears_confirmation(self):
        backend = Backend(); model = InstallerModel(backend.choice, backend)
        self.assertIsNone(model.action('1')); self.assertEqual(model.page, 'review')
        self.assertIsNone(model.action('b')); self.assertIsNone(model.accepted)

    def test_separate_confirmation_rereads_current_disk(self):
        backend = Backend(); model = InstallerModel(backend.choice, backend)
        model.action('1'); accepted = model.action('i')
        self.assertEqual(backend.reads, 2); self.assertEqual(accepted['action'], 'install')
        self.assertEqual(model.page, 'progress')

    def test_gate_blocks_confirmation(self):
        backend = Backend(); backend.available = False; backend.reason = 'physical gate'
        model = InstallerModel(backend.choice, backend); model.action('1')
        self.assertIsNone(model.action('i')); self.assertEqual(model.page, 'review')
        self.assertIn('physical gate', '\n'.join(model.lines()))

    def test_changed_disk_is_not_confirmed(self):
        backend = Backend(); model = InstallerModel(backend.choice, backend); model.action('1')
        backend.snapshot['table']['partitions'][0]['start'] += 1
        with self.assertRaises(ValueError): model.action('i')
        self.assertNotEqual(model.page, 'progress')

    def test_resume_needs_saved_intent_and_separate_confirmation(self):
        backend = Backend(); model = InstallerModel(backend.choice, backend)
        self.assertIsNone(model.action('2')); self.assertEqual(model.page, 'home')
        backend.record = prepare_intent(backend.choice, backend.snapshot, review(backend.choice, [backend.snapshot]), {'table': backend.snapshot['table']})
        self.assertIsNone(model.action('2')); self.assertEqual(model.page, 'resume')
        self.assertEqual(model.action('i')['action'], 'resume')

    def test_resources_do_not_change_installation_choice(self):
        backend = Backend(); original = copy.deepcopy(backend.choice); model = InstallerModel(backend.choice, backend)
        self.assertIsNone(model.action('3')); self.assertEqual(model.page, 'resources')
        self.assertEqual(backend.choice, original); self.assertIsNone(model.accepted)


if __name__ == '__main__': unittest.main(verbosity=2)
