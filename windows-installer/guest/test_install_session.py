"""A Windows preview cannot authorize installation or conceal changed metadata."""
import copy
import unittest
from test_handoff import fixture
from install_session import review, accept_current


class InstallSessionChecks(unittest.TestCase):
    def test_exact_fresh_confirmation_is_separate_from_preview(self):
        selection, item = fixture(); candidates = [item]
        accepted = review(selection, candidates)
        self.assertEqual(accepted['action'], 'install')
        self.assertIs(selection['allow_disk_write'], False)
        self.assertEqual(accept_current(selection, candidates, accepted), accepted)

    def test_decline_or_changed_review_refused(self):
        selection, item = fixture(); candidates = [item]
        with self.assertRaises(RuntimeError): accept_current(selection, candidates, None)
        accepted = review(selection, candidates); accepted['range']['size'] -= 1024**2
        with self.assertRaises(RuntimeError): accept_current(selection, candidates, accepted)

    def test_layout_change_after_confirmation_refused(self):
        selection, item = fixture(); candidates = [item]; accepted = review(selection, candidates)
        changed = copy.deepcopy(candidates); changed[0]['table']['partitions'][0]['start'] += 1
        with self.assertRaises(ValueError): accept_current(selection, changed, accepted)

    def test_live_node_change_requires_new_confirmation(self):
        selection, item = fixture(); candidates = [item]; accepted = review(selection, candidates)
        changed = copy.deepcopy(candidates); changed[0]['table']['device'] = '/dev/nvme8n1'
        with self.assertRaises(RuntimeError): accept_current(selection, changed, accepted)


if __name__ == '__main__': unittest.main(verbosity=2)
