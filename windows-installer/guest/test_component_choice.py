"""Consent/source binding only; synthetic 3.10 is not runtime acceptance."""
import copy
import unittest
import uuid
from test_handoff import fixture
from component_choice import selected, request, HDR_SOURCE
from install_session import review, accept_current, prepare_intent, resume_review
from ui_model import InstallerModel
from test_ui_model import Backend

class ComponentChoices(unittest.TestCase):
    def choice(self):
        value, disk = fixture()
        value.update(source={'version':'3.8.14','build':'20260707.10'}, resources=['hdr'], components=[], plugins=[])
        return value, disk
    def test_carriage_does_not_request_or_enable_component(self):
        value, disk = self.choice(); operation = str(uuid.uuid4())
        self.assertEqual(selected(value), [])
        self.assertEqual(request(value, operation)['components'], [])
        self.assertEqual(review(value, [disk])['components'], [])
    def test_unknown_duplicate_plugin_and_incompatible_refuse_before_review(self):
        value, disk = self.choice()
        for changes in ({'components':['bad']}, {'components':['hdr','hdr']}, {'components':['hdr']}, {'plugins':['decky']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): review(dict(value, **changes), [disk])
    def test_compatible_metadata_still_requires_resource(self):
        value, disk = self.choice(); value.update(source=copy.deepcopy(HDR_SOURCE), components=['hdr'], resources=[])
        with self.assertRaises(ValueError): review(value, [disk])
    def test_changed_choice_invalidates_earlier_confirmation(self):
        value, disk = self.choice(); value['source'] = copy.deepcopy(HDR_SOURCE)
        before = review(value, [disk]); value['components'] = ['hdr']
        with self.assertRaises(RuntimeError): accept_current(value, [disk], before)
    def test_same_operation_id_source_and_explicit_choice_are_preserved(self):
        value, disk = self.choice(); value.update(source=copy.deepcopy(HDR_SOURCE), components=['hdr'])
        operation = str(uuid.uuid4()); record = request(value, operation)
        self.assertEqual(record['id'], operation); self.assertEqual(record['components'], ['hdr'])
        value['components'].clear(); self.assertEqual(record['components'], ['hdr'])
    def test_only_legacy_empty_confirmation_is_compatible(self):
        value, disk = self.choice(); old = review(value, [disk]); del old['components']
        self.assertEqual(accept_current(value, [disk], old)['components'], [])
        value.update(source=copy.deepcopy(HDR_SOURCE), components=['hdr'])
        with self.assertRaises(RuntimeError): accept_current(value, [disk], old)
    def test_review_and_resource_page_show_explicit_none(self):
        backend = Backend(); backend.choice['resources'] = ['hdr']
        model = InstallerModel(backend.choice, backend); model.action('1')
        self.assertIn('Firstboot components: none', model.lines())
        model.action('b'); model.action('3')
        self.assertIn('Firstboot choices: none', model.lines())
        self.assertEqual(backend.choice.get('components', []), [])

if __name__ == '__main__': unittest.main(verbosity=2)
