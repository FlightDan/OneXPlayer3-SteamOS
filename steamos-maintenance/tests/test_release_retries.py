import http.client
import json
import ssl
import unittest
from unittest import mock
import urllib.error

from oxp3_maintenance import releases as r
from test_releases import Response, release


class ReleaseRetryTests(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(r.time, 'sleep')
        self.delay = self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_transient_connection_failure_retries_and_reports_worker_progress(self):
        events = []
        opener = mock.Mock(spec=lambda request, timeout: None, side_effect=[urllib.error.URLError('temporary DNS failure'),
                                       Response(json.dumps([release('1.1.0')]).encode())])
        result = r.check_releases('1.0.0', 'stable', opener=opener, progress=events.append)
        self.assertEqual(result['status'], 'update_available')
        self.assertEqual(opener.call_count, 2)
        self.delay.assert_called_once_with(0.5)
        self.assertEqual([item['phase'] for item in events], ['contacting_github', 'retrying_github', 'contacting_github'])
        self.assertEqual(events[-1]['attempt'], 2)
        self.assertTrue(all('url' not in item for item in events))

    def test_exhausted_network_error_stays_failure_never_up_to_date(self):
        opener = mock.Mock(spec=lambda request, timeout: None, side_effect=TimeoutError('socket timeout'))
        with self.assertRaises(r.ReleaseError) as caught:
            r.check_releases('1.0.0', 'stable', opener=opener)
        # API exhausts two attempts; its advisory feed fallback also exhausts
        # two. Failure must still never become an up-to-date result.
        self.assertEqual(opener.call_count, 4)
        self.assertEqual(caught.exception.code, 'network_unavailable')
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(self.delay.call_count, 2)

    def test_temporary_github_http_errors_retry_once(self):
        for status in (408, 500, 502, 503, 504):
            with self.subTest(status=status):
                opener = mock.Mock(spec=lambda request, timeout: None, side_effect=[urllib.error.HTTPError(r.API_URL, status, 'temporary', {}, None), Response(b'[]')])
                with r._request(r.API_URL, opener) as response:
                    self.assertEqual(response.read(), b'[]')
                self.assertEqual(opener.call_count, 2)

    def test_rate_limit_and_not_found_do_not_retry_connection(self):
        for status, code in ((403, 'rate_limited'), (429, 'rate_limited'), (404, 'release_unavailable'), (401, 'http_error')):
            with self.subTest(status=status):
                opener = mock.Mock(spec=lambda request, timeout: None, side_effect=urllib.error.HTTPError(r.API_URL, status, 'permanent', {}, None))
                with self.assertRaises(r.ReleaseError) as caught:
                    r._request(r.API_URL, opener)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(opener.call_count, 1)
        self.delay.assert_not_called()

    def test_certificate_failure_never_retries_or_falls_back(self):
        for error in (ssl.SSLCertVerificationError('invalid certificate'),
                      urllib.error.URLError(ssl.SSLCertVerificationError('invalid certificate'))):
            with self.subTest(error=type(error).__name__):
                opener = mock.Mock(spec=lambda request, timeout: None, side_effect=error)
                with self.assertRaises(r.ReleaseError) as caught:
                    r.check_releases('1.0.0', 'stable', opener=opener)
                self.assertEqual(caught.exception.code, 'tls_verification_failed')
                self.assertFalse(caught.exception.retryable)
                self.assertEqual(opener.call_count, 1)
        self.delay.assert_not_called()

    def test_unsafe_redirect_or_signature_failure_is_not_transport_retryable(self):
        opener = mock.Mock(spec=lambda request, timeout: None, side_effect=r.ReleaseError('Unsafe redirect'))
        with self.assertRaises(r.ReleaseError):
            r._request(r.API_URL, opener)
        self.assertEqual(opener.call_count, 1)
        self.delay.assert_not_called()

    def test_incomplete_metadata_stream_remains_explicit_failure(self):
        class Broken(Response):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b'', 20)
        opener = mock.Mock(spec=lambda request, timeout: None, return_value=Broken(b''))
        with self.assertRaisesRegex(r.ReleaseError, 'Reading GitHub release data failed'):
            r.check_releases('1.0.0', 'stable', opener=opener)
        self.assertEqual(opener.call_count, 1)

    def test_incomplete_catalog_has_localizable_error_without_verification_or_retry(self):
        class Broken(Response):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b'', 20)
        prefix = 'https://github.com/' + r.REPOSITORY + '/releases/download/v1.1.0/oxp3-maintenance-1.1.0-catalog.'
        opener = mock.Mock(spec=lambda request, timeout: None, return_value=Broken(b'', url=prefix + 'json'))
        candidate = {'version': '1.1.0', 'catalog_urls': {suffix: prefix + suffix for suffix in ('json', 'sig')}}
        with self.assertRaises(r.ReleaseError) as caught:
            r.fetch_catalog(candidate, 'unused-key', opener=opener)
        self.assertEqual(caught.exception.code, 'network_read_failed')
        self.assertEqual(opener.call_count, 1)

    def test_worker_can_cancel_before_another_connection_attempt(self):
        class Cancelled(Exception):
            pass
        opener = mock.Mock(spec=lambda request, timeout: None, side_effect=TimeoutError())
        def progress(event):
            if event['phase'] == 'retrying_github':
                raise Cancelled()
        with self.assertRaises(Cancelled):
            r._request(r.API_URL, opener, progress=progress)
        self.assertEqual(opener.call_count, 1)
        self.delay.assert_not_called()

    def test_malformed_api_metadata_never_triggers_advisory_fallback(self):
        opener = mock.Mock(spec=lambda request, timeout: None, return_value=Response(b'not JSON'))
        with self.assertRaisesRegex(r.ReleaseError, 'unreadable release data'):
            r.check_releases('1.0.0', 'stable', opener=opener)
        self.assertEqual(opener.call_count, 1)
        self.delay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
