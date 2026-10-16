from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import downloads
from oxp3_maintenance.bundle import BundleError
from oxp3_maintenance.releases import REPOSITORY


class DownloadProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / 'public.pem'
        self.key.write_text('fixture')
        base = 'https://github.com/' + REPOSITORY + '/releases/download/v1.0.0/'
        self.candidate = {'version': '1.0.0', 'asset_name': 'oxp3-maintenance-1.0.0-linux-x86_64.tar.gz',
                          'download_url': base + 'oxp3-maintenance-1.0.0-linux-x86_64.tar.gz',
                          'catalog_urls': {suffix: base + 'oxp3-maintenance-1.0.0-catalog.' + suffix for suffix in ('json', 'sig')}}

    def test_save_forwards_same_progress_callback_to_catalog_and_archive(self):
        events = []
        progress = events.append
        def fetch(*args, **kwargs):
            kwargs['progress']({'phase': 'contacting_github', 'attempt': 1, 'attempts': 2})
            return {'signed': 'catalog'}
        def download(url, destination, **kwargs):
            kwargs['progress']({'phase': 'contacting_github', 'attempt': 1, 'attempts': 2})
            Path(destination).write_bytes(b'fixture bundle')
        with mock.patch.object(downloads, 'fetch_catalog', side_effect=fetch) as catalog, \
             mock.patch.object(downloads, 'download_bundle', side_effect=download) as archive, \
             mock.patch.object(downloads, '_check', return_value={'release': {'version': '1.0.0'}}) as check:
            result = downloads.save(self.candidate, self.root / 'saved', key=self.key, progress=progress)
        self.assertIs(catalog.call_args.kwargs['progress'], progress)
        self.assertIs(archive.call_args.kwargs['progress'], progress)
        self.assertEqual(check.call_args.args[3], {'signed': 'catalog'})
        self.assertEqual(Path(result['path']).read_bytes(), b'fixture bundle')
        self.assertEqual(len(events), 2)

    def test_progress_cancellation_cannot_publish_unverified_download(self):
        class Cancelled(Exception):
            pass
        def cancel(event):
            raise Cancelled()
        opener = mock.Mock(spec=lambda request, timeout: None)
        with self.assertRaises(Cancelled):
            downloads.save(self.candidate, self.root / 'saved', key=self.key, opener=opener, progress=cancel)
        opener.assert_not_called()
        self.assertFalse((self.root / 'saved').exists())

    def test_signature_failure_never_downloads_archive_even_with_progress_enabled(self):
        with mock.patch.object(downloads, 'fetch_catalog', side_effect=BundleError('invalid signature')), \
             mock.patch.object(downloads, 'download_bundle') as archive:
            with self.assertRaises(BundleError):
                downloads.save(self.candidate, self.root / 'saved', key=self.key, progress=lambda event: None)
        archive.assert_not_called()
        self.assertFalse((self.root / 'saved').exists())


if __name__ == '__main__':
    unittest.main()
