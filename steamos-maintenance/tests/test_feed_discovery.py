"""Quota-free fallback discovery with in-memory HTTP and real test signatures."""
import base64
import json
from pathlib import Path
import unittest
from unittest import mock
import urllib.error
from xml.sax.saxutils import escape

import build_bundle as builder
from oxp3_maintenance import catalog, releases as r
import test_bundle
from test_releases import Response, release


def feed(tags):
    entries = []
    for tag in tags:
        url = tag if tag.startswith('http') else 'https://github.com/' + r.REPOSITORY + '/releases/tag/' + tag
        entries.append('<entry><title>Project ' + escape(tag) + '</title><link rel="alternate" href="' + escape(url, {'"': '&quot;'}) + '"/><updated>2026-10-15T00:00:00Z</updated></entry>')
    return ('<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(entries) + '</feed>').encode()


class FeedDiscoveryTests(unittest.TestCase):
    _openssl_adapter = test_bundle.BundleTests._openssl_adapter
    _sign = test_bundle.BundleTests._sign

    def setUp(self):
        test_bundle.BundleTests.setUp(self)
        self.requests = []
        self.feed = feed(['v1.2.3'])
        self.assets = {}
        self.api_status = 403

    def signed(self, version, *, signature=None):
        value = {'schema': 1, 'release': {'version': version,
            'display_version': 'Signed ' + version, 'channel': 'beta' if '-' in version else 'stable'},
            'bundle': {'name': 'oxp3-maintenance-' + version + '-linux-x86_64.tar.gz',
                       'size': 12345, 'sha256': 'a' * 64, 'manifest_digest': 'b' * 64},
            'components': [{'id': 'keyboard', 'kind': 'repairs', 'zh': '键盘', 'en': 'Keyboard',
                'delivery': 'maintenance', 'available': True, 'dependencies': []}]}
        raw = catalog.canonical(value)
        prefix = 'https://github.com/' + r.REPOSITORY + '/releases/download/v' + version + '/oxp3-maintenance-' + version + '-catalog.'
        self.assets[prefix + 'json'] = raw
        self.assets[prefix + 'sig'] = self._sign(raw) if signature is None else signature
        return value

    def opener(self, request, timeout):
        self.assertEqual(timeout, 30)
        self.assertNotIn('Authorization', dict(request.headers))
        url = request.full_url
        self.requests.append(url)
        if url.startswith(r.API_URL + '?'):
            raise urllib.error.HTTPError(url, self.api_status, 'HTTP fixture', {}, None)
        if url == r.ATOM_URL:
            self.assertEqual(request.get_header('Accept'), 'application/atom+xml')
            return Response(self.feed, url=url)
        if url in self.assets:
            return Response(self.assets[url], url=url)
        raise urllib.error.HTTPError(url, 404, 'No catalog', {}, None)

    def check(self, installed='1.0.0', channel='stable', **kwargs):
        return r.check_releases(installed, channel, opener=self.opener, public_key=kwargs.get('public_key', self.public))

    def test_rate_limit_feed_needs_signed_catalog_before_offering_package(self):
        value = self.signed('1.2.3')
        report = self.check()
        self.assertEqual(report['discovery_source'], 'github_atom')
        self.assertEqual(report['status'], 'update_available')
        self.assertTrue(report['latest_project']['advisory'])
        candidate = report['candidates'][0]
        self.assertEqual(candidate['version'], '1.2.3')
        self.assertEqual(candidate['size'], value['bundle']['size'])
        self.assertEqual(candidate['asset_name'], value['bundle']['name'])
        self.assertTrue(candidate['catalog_verified'])
        self.assertEqual(candidate['display_version'], 'Signed 1.2.3')
        self.assertFalse(any(url.endswith('.tar.gz') for url in self.requests))

    def test_missing_key_reports_latest_project_with_unknown_package_availability(self):
        report = self.check(public_key=self.root / 'missing.pem')
        self.assertEqual(report['latest_project']['version'], '1.2.3')
        self.assertEqual(report['status'], 'maintenance_availability_unknown')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(self.requests, [r.API_URL + '?per_page=100&page=1', r.ATOM_URL])

    def test_missing_catalog_is_pending_never_fabricated_or_up_to_date(self):
        report = self.check(installed='1.2.3')
        self.assertEqual(report['status'], 'maintenance_package_pending')
        self.assertEqual(report['maintenance_releases'], [])
        self.assertIsNone(report['latest_maintenance'])
        self.assertIn('No signed maintenance catalog', report['warning'])

    def test_bad_signature_is_explicit_unknown_warning(self):
        self.signed('1.2.3', signature=base64.b64encode(b'\0' * 64))
        report = self.check(installed='1.2.3')
        self.assertEqual(report['status'], 'maintenance_availability_unknown')
        self.assertIn('verification failed', report['warning'])
        self.assertEqual(report['candidates'], [])

    def test_signed_wrong_tag_version_cannot_offer_bundle(self):
        self.signed('1.2.2')
        old = '/v1.2.2/oxp3-maintenance-1.2.2-catalog.'
        for suffix in ('json', 'sig'):
            url = next(url for url in self.assets if url.endswith('.' + suffix))
            self.assets[url.replace(old, '/v1.2.3/oxp3-maintenance-1.2.3-catalog.')] = self.assets[url]
        report = self.check()
        self.assertEqual(report['status'], 'maintenance_availability_unknown')
        self.assertIn('wrong release', report['warning'])
        self.assertEqual(report['candidates'], [])

    def test_eligible_stable_beta_order_and_catalog_probe_limit(self):
        self.feed = feed(['v1.9.0', 'v1.10.0', 'v2.0.0-beta.2', 'v2.0.0-beta.10', 'v3.0.0-alpha.1'])
        for version in ('1.9.0', '1.10.0', '2.0.0-beta.2', '2.0.0-beta.10'):
            self.signed(version)
        report = self.check(channel='beta')
        self.assertEqual([item['version'] for item in report['maintenance_releases']],
                         ['2.0.0-beta.10', '2.0.0-beta.2', '1.10.0'])
        self.assertEqual(len([url for url in self.requests if url.endswith('-catalog.json')]), 3)
        self.requests.clear()
        report = self.check(channel='stable')
        self.assertEqual([item['version'] for item in report['candidates']], ['1.10.0', '1.9.0'])

    def test_foreign_noncanonical_and_invalid_feed_links_cannot_redirect_catalog_fetch(self):
        self.feed = feed(['https://github.com/evil/repo/releases/tag/v99.0.0',
            'https://github.com/' + r.REPOSITORY + '/releases/tag/v8.0.0?x=1',
            'https://github.com/' + r.REPOSITORY + '/releases/tag/%76' + '7.0.0',
            'v01.2.3', 'v1.2.3'])
        report = self.check()
        self.assertEqual(report['latest_project']['version'], '1.2.3')
        self.assertFalse(any('/evil/' in url or '99.0.0' in url or '%76' in url for url in self.requests))

    def test_dtd_entity_malformed_and_oversize_feed_preserve_original_rate_limit(self):
        for raw in (b'<!DOCTYPE feed [<!ENTITY x "bad">]><feed/>',
                    b'<!ENTITY x "bad"><feed/>', b'not XML', b'\0<feed/>'):
            with self.subTest(raw=raw):
                self.feed = raw
                with self.assertRaisesRegex(r.ReleaseError, 'rate limited') as result:
                    self.check()
                self.assertEqual(result.exception.http_status, 403)
        self.feed = b'x' * 11
        with mock.patch.object(r, 'MAX_FEED_BYTES', 10):
            with self.assertRaisesRegex(r.ReleaseError, 'rate limited'):
                self.check()

    def test_exhausted_transient_http_api_failure_uses_same_authenticated_feed_path(self):
        self.api_status = 500
        with mock.patch.object(r.time, 'sleep'):
            result = self.check()
        self.assertEqual(result['discovery_source'], 'github_atom')
        self.assertEqual(result['api_error_code'], 'github_unavailable')
        self.assertEqual(result['status'], 'maintenance_package_pending')
        self.assertEqual(len([url for url in self.requests if url.startswith(r.API_URL)]), r.REQUEST_ATTEMPTS)
        self.assertEqual(result['candidates'], [])

    def test_exhausted_network_api_failure_still_requires_signed_catalog(self):
        self.signed('1.2.3')
        def opener(request, timeout):
            if request.full_url.startswith(r.API_URL):
                self.requests.append(request.full_url)
                raise urllib.error.URLError('temporary network failure')
            return self.opener(request, timeout)
        with mock.patch.object(r.time, 'sleep'):
            result = r.check_releases('1.0.0', 'stable', opener=opener, public_key=self.public)
        self.assertEqual(result['discovery_source'], 'github_atom')
        self.assertEqual(result['api_error_code'], 'network_unavailable')
        self.assertTrue(result['candidates'][0]['catalog_verified'])
        self.assertEqual(len([url for url in self.requests if url.startswith(r.API_URL)]), 2)

    def test_429_also_falls_back_and_unavailable_feed_preserves_api_error(self):
        self.api_status = 429
        self.assertEqual(self.check()['discovery_source'], 'github_atom')
        def unavailable(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403 if request.full_url.startswith(r.API_URL) else 404, 'Unavailable', {}, None)
        with self.assertRaisesRegex(r.ReleaseError, 'rate limited'):
            r.check_releases('1.0.0', 'stable', opener=unavailable)

    def test_existing_api_success_contract_does_not_consult_feed(self):
        requests = []
        def success(request, timeout):
            requests.append(request.full_url)
            return Response(json.dumps([release('1.2.3')]).encode())
        report = r.check_releases('1.0.0', 'stable', opener=success)
        self.assertEqual(report['candidates'][0]['version'], '1.2.3')
        self.assertEqual(len(requests), 1)


if __name__ == '__main__':
    unittest.main()
