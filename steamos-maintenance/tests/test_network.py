import hashlib
import http.client
import io
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request

from oxp3_maintenance import network as n, releases as r, distribution as d
from oxp3_maintenance.bundle import BundleError

API = r.API_URL + '?per_page=100&page=1'
ASSET = 'https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6/oxp3-maintenance-1.0.6-linux-x86_64.tar.gz'
COMPONENT = 'https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6/oxp3-package-test-0123456789abcdef.tar.gz'


class Response(io.BytesIO):
    def __init__(self, raw, url, headers=None, status=200):
        super().__init__(raw)
        self.url, self.status = url, status
        self.headers = headers or {'Content-Length': str(len(raw))}

    def geturl(self):
        return self.url


class NetworkTests(unittest.TestCase):
    def policy(self, mode, action):
        calls = []
        def factory(handler):
            def request(request, timeout):
                calls.append(request)
                self.assertLessEqual(timeout, 15)
                return action(request, handler)
            return mock.Mock(open=request)
        return n.NetworkPolicy(mode, opener_factory=factory), calls

    def test_auto_timeout_falls_back_and_keeps_canonical_identity(self):
        def action(request, handler):
            if request.full_url == ASSET:
                raise TimeoutError()
            return Response(b'archive bytes', request.full_url)
        policy, calls = self.policy('auto', action)
        with policy.open(ASSET) as response:
            self.assertEqual(response.geturl(), ASSET)
            self.assertEqual(response.read(2) + response.read(), b'archive bytes')
        self.assertEqual([x.full_url for x in calls], [ASSET, 'https://gh-proxy.com/' + ASSET])

    def test_html_and_broken_sniff_fall_back(self):
        def action(request, handler):
            if request.full_url.startswith('https://ghfast.top/'):
                return Response(b'<!doctype html>captcha', request.full_url)
            return Response(b'ok', request.full_url)
        policy, calls = self.policy('ghfast.top', action)
        self.assertEqual(policy.open(ASSET).read(), b'ok')
        self.assertEqual(len(calls), 2)

    def test_api_only_uses_tested_metadata_route_and_atom_direct(self):
        policy, calls = self.policy('ghfast.top', lambda request, handler: Response(b'[]', request.full_url))
        self.assertEqual(policy.routes(API), ('direct', 'gh-proxy.com'))
        self.assertEqual(policy.routes(r.ATOM_URL), ('direct',))
        with policy.open(API) as response:
            self.assertEqual(response.read(), b'[]')
        policy, calls = self.policy('gh-proxy.com', lambda request, handler: Response(b'[]', request.full_url))
        self.assertEqual(policy.open(API).geturl(), API)

    def test_direct_never_uses_proxy_and_preserves_http_error(self):
        def action(request, handler):
            raise urllib.error.HTTPError(request.full_url, 403, 'limited', {}, None)
        policy, calls = self.policy('direct', action)
        with self.assertRaises(urllib.error.HTTPError):
            policy.open(API)
        self.assertEqual(len(calls), 1)

    def test_rejects_credentials_custom_headers_non_github_and_unsupported_api(self):
        policy, calls = self.policy('auto', lambda *args: self.fail('network called'))
        bad = ['https://example.org/file', 'https://github.com.evil.example/file',
               ASSET.replace('https://', 'http://'), ASSET.replace('https://', 'https://token@'),
               ASSET + '?token=secret', API + '&access_token=secret',
               'https://api.github.com/user', 'https://ghfast.top/' + ASSET,
               ASSET.replace('github.com', 'github.com:444'), ASSET + '#fragment',
               ASSET.replace('FlightDan', 'other'), ASSET + '\\escape']
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                policy.open(url)
        for header in ('Authorization', 'Cookie', 'Proxy-Authorization', 'X-Private-Token'):
            with self.subTest(header=header), self.assertRaises(ValueError):
                policy.open(urllib.request.Request(ASSET, headers={header: 'private'}))
        self.assertEqual(calls, [])

    def test_rejects_untrusted_and_downgraded_redirects_every_hop(self):
        handler = n._Redirect(ASSET, 'ghfast.top')
        for url in ('http://ghfast.top/' + ASSET, 'https://evil.example/file',
                    'https://release-assets.githubusercontent.com.evil.example/file',
                    'https://ghproxy.net/' + ASSET, 'https://token@release-assets.githubusercontent.com/a'):
            with self.subTest(url=url), self.assertRaises(n.NetworkError):
                handler.redirect_request(None, None, 302, '', {}, url)
        self.assertTrue(n._transfer_allowed('https://release-assets.githubusercontent.com/a?signed=1', ASSET, 'direct'))
        self.assertFalse(n._transfer_allowed('https://gh-proxy.com/' + r.ATOM_URL, r.ATOM_URL, 'direct'))

    def test_malicious_final_url_cannot_be_hidden_by_normalization(self):
        policy, calls = self.policy('direct', lambda request, handler: Response(b'archive', 'https://evil.example/file'))
        with self.assertRaises(n.NetworkError):
            policy.open(ASSET)

    def test_tls_failure_fallback_has_no_certificate_bypass(self):
        def action(request, handler):
            if request.full_url == ASSET:
                raise urllib.error.URLError(ssl.SSLCertVerificationError('bad cert'))
            self.assertTrue(request.full_url.startswith('https://'))
            return Response(b'ok', request.full_url)
        policy, calls = self.policy('auto', action)
        self.assertEqual(policy.open(ASSET).read(), b'ok')
        self.assertEqual(len(calls), 2)
        # Production factory is the standard verified HTTPS opener: no context
        # override or unverified TLS handler is supplied to build_opener.
        with mock.patch.object(n.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value = Response(b'ok', ASSET)
            self.assertEqual(n.NetworkPolicy('direct').open(ASSET).read(), b'ok')
            args, kwargs = factory.call_args
            self.assertEqual(kwargs, {})
            self.assertEqual(len(args), 1)
            self.assertIsInstance(args[0], n._Redirect)

    def test_signed_component_hash_and_size_still_reject_tampering_and_truncation(self):
        original = b'expected immutable signed content'
        ref = dict(url=COMPONENT, size=len(original), sha256=hashlib.sha256(original).hexdigest())
        for raw in (b'x' * len(original), original[:-1], original + b'x'):
            policy, calls = self.policy('ghfast.top', lambda request, handler: Response(raw, request.full_url))
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'component'
                with self.assertRaises(BundleError):
                    d._download(ref, target, opener=policy.open)
                self.assertFalse(target.exists())

    def test_bundle_truncation_is_rejected_and_partial_file_removed(self):
        policy, calls = self.policy('direct', lambda request, handler: Response(b'short', request.full_url, {'Content-Length': '100'}))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bundle'
            with self.assertRaises(r.ReleaseError):
                r.download_bundle(ASSET, target, opener=policy.open)
            self.assertFalse(target.exists())

    def test_unsolicited_partial_response_is_rejected(self):
        policy, _ = self.policy('direct', lambda request, handler: Response(b'partial', request.full_url, status=206))
        with self.assertRaises(n.NetworkError):
            policy.open(ASSET)

    def test_mode_enum_and_invalid_env(self):
        self.assertEqual(n.mode_from_env({}), 'auto')
        self.assertEqual([option['id'] for option in n.policy_options()], list(n.NETWORK_MODES))
        with self.assertRaises(ValueError):
            n.mode_from_env({'OXP3_GITHUB_NETWORK': 'https://evil.example'})
        with self.assertRaises(ValueError):
            n.NetworkPolicy('https://evil.example')


if __name__ == '__main__':
    unittest.main()
