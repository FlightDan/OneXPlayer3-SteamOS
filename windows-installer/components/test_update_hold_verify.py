"""Missing/tampered protection must fail the image verification gate."""
import os
import unittest

import test_update_hold as fixtures
import update_hold_verify


class VerificationChecks(unittest.TestCase):
    put = fixtures.CandidateChecks.put
    link = fixtures.CandidateChecks.link
    snapshot = fixtures.CandidateChecks.snapshot

    def setUp(self):
        fixtures.CandidateChecks.setUp(self)
        output = fixtures.hold.files(self.root)
        for relative, metadata in output.items():
            self.put(relative, metadata['data'])
            (self.root / relative).chmod(metadata['mode'])
        self.report = {'status': 'files_installed', 'os_image_updates': 'held',
                       'steam_client_updates': 'unchanged', 'files': list(output)}

    def test_valid_readonly_check_and_missing_file_refused(self):
        before = self.snapshot()
        self.assertEqual(update_hold_verify.verify(self.root, self.report), 18)
        self.assertEqual(self.snapshot(), before)
        # The builder alone can generate a missing file. Verification must
        # additionally prove it has actually been installed.
        (self.root / fixtures.hold.DROPIN).unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
            update_hold_verify.verify(self.root, self.report)

    def test_changed_feed_and_bad_reports_refused(self):
        for report in (None, {}, {**self.report, 'status': 'not_installed'},
                       {**self.report, 'os_image_updates': 'allowed'},
                       {**self.report, 'steam_client_updates': 'held'},
                       {**self.report, 'files': self.report['files'][:-1]},
                       {**self.report, 'files': [self.report['files'][0]] * 18},
                       {**self.report, 'files': [None] * 18}):
            with self.subTest(report=report), self.assertRaises(RuntimeError):
                update_hold_verify.verify(self.root, report)
        feed = next(path for path in self.report['files'] if path.endswith('.json'))
        self.put(feed, b'{"changed":true}\n')
        with self.assertRaises(RuntimeError):
            update_hold_verify.verify(self.root, self.report)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'Unix ownership verification requires Linux root')
    def test_nonroot_group_on_installed_file_refused(self):
        # Builder guards UID and writable permissions; verification additionally
        # requires the exact root group promised by the installation transaction.
        os.chown(self.root / fixtures.hold.DROPIN, 0, 1000)
        with self.assertRaisesRegex(RuntimeError, 'permissions changed'):
            update_hold_verify.verify(self.root, self.report)


if __name__ == '__main__': unittest.main()
