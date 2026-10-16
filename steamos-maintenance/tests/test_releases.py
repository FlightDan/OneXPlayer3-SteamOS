import io
import itertools
import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

from oxp3_maintenance import releases as r


def release(version, **changes):
    name = "oxp3-maintenance-%s-linux-x86_64.tar.gz" % version
    value = {"tag_name": "v" + version, "name": "Release " + version,
             "draft": False, "prerelease": "-" in version,
             "assets": [{"name": name, "size": 100,
                         "browser_download_url": "https://github.com/" + r.REPOSITORY + "/releases/download/v" + version + "/" + name}]}
    value.update(changes)
    return value


class Response(io.BytesIO):
    def __init__(self, content, *, url=None, length=None):
        super().__init__(content)
        self.url = url
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def geturl(self):
        return self.url


class ReleaseTests(unittest.TestCase):
    def test_semver_numeric_order_and_stable_filter(self):
        values = [release(v) for v in ["1.9.0", "1.10.0", "2.0.0-beta.2", "2.0.0-beta.10", "1.0.0"]]
        self.assertEqual([v["version"] for v in r.release_candidates(values, "1.0.0", "stable")], ["1.10.0", "1.9.0"])
        self.assertEqual([v["version"] for v in r.release_candidates(values, "1.0.0", "beta")], ["2.0.0-beta.10", "2.0.0-beta.2", "1.10.0", "1.9.0"])

    def test_beta_upgrade_to_stable(self):
        values = [release("2.0.0-beta.1"), release("2.0.0"), release("2.0.0-alpha.1")]
        self.assertEqual([v["version"] for v in r.release_candidates(values, "2.0.0-beta.1", "beta")], ["2.0.0"])

    def test_no_equal_build_metadata_upgrade(self):
        self.assertEqual(r.release_candidates([release("1.2.3+new")], "1.2.3+old", "stable"), [])

    def test_maintenance_revision_numeric_order_ignores_input_and_publication_order(self):
        versions = ['0.1.4', '0.1.4+maintenance.1', '0.1.4+maintenance.9', '0.1.4+maintenance.10']
        for order in itertools.permutations(versions):
            values = [release(v, published_at='2099-01-01' if v == '0.1.4' else '2000-01-01') for v in order]
            report = r.check_releases('0.1.4+maintenance.1', 'stable',
                                      opener=lambda *a, **kw: Response(json.dumps(values).encode()))
            self.assertEqual([v['version'] for v in report['maintenance_releases']], list(reversed(versions)))
            self.assertEqual([v['version'] for v in report['candidates']], list(reversed(versions[2:])))
            self.assertEqual(report['latest_project']['version'], versions[-1])
            self.assertEqual(report['status'], 'update_available')

    def test_revision_policy_preserves_semver_and_only_recognizes_canonical_suffix(self):
        self.assertEqual(r._Version('0.1.4+maintenance.10'), r._Version('0.1.4'))
        for suffix in ['other.99', 'maintenance.01', 'maintenance.0', 'maintenance.10.extra', 'Maintenance.10']:
            self.assertEqual(r._release_order('0.1.4+' + suffix), r._release_order('0.1.4'))
        self.assertLess(r._release_order('0.1.4+maintenance.999'), r._release_order('0.1.5'))
        self.assertLess(r._release_order('0.1.4-beta.10+maintenance.999'), r._release_order('0.1.4'))
        self.assertLess(r._release_order('0.1.4-beta.9+maintenance.999'), r._release_order('0.1.4-beta.10'))
        values = [release('0.1.4+maintenance.10'), release('0.1.4+maintenance.9'), release('0.1.4')]
        self.assertEqual(r.release_candidates(values, '0.1.4+maintenance.10', 'stable'), [])
        self.assertEqual(len(r.release_candidates(values, '0.1.4+maintenance.10', 'stable', include_current=True)), 1)

    def test_newer_windows_only_project_does_not_hide_latest_maintenance(self):
        values = [release('0.1.5', assets=[]), release('0.1.4'), release('0.1.4+maintenance.4')]
        report = r.check_releases('0.1.4+maintenance.3', 'stable',
                                  opener=lambda *a, **kw: Response(json.dumps(values).encode()))
        self.assertEqual(report['latest_project']['version'], '0.1.5')
        self.assertEqual(report['latest_maintenance']['version'], '0.1.4+maintenance.4')
        self.assertEqual(report['status'], 'maintenance_package_pending')

    def test_drafts_missing_bundle_and_invalid_tags_excluded(self):
        values = [release("2.0.0", draft=True), release("3.0.0", assets=[]), release("01.2.3"),
                  release("3.0.0-beta.01"), release("4.0.0", prerelease=True)]
        self.assertEqual(r.release_candidates(values, "1.0.0", "beta"), [])

    def test_wrong_repo_url_and_asset_name_excluded(self):
        item = release("2.0.0")
        item["assets"][0]["browser_download_url"] = item["assets"][0]["browser_download_url"].replace(r.REPOSITORY, "evil/repo")
        self.assertEqual(r.release_candidates([item], "1.0.0", "stable"), [])
        item = release("2.0.0")
        item["assets"][0]["name"] = "source.tar.gz"
        self.assertEqual(r.release_candidates([item], "1.0.0", "stable"), [])

    def test_invalid_channel_and_installed_metadata(self):
        for installed, channel in [("garbage", "stable"), ("1.0.0", "nightly")]:
            with self.assertRaises(r.ReleaseError):
                r.release_candidates([], installed, channel)

    def test_paginated_releases_no_latest_or_token(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            self.assertEqual(timeout, 30)
            return Response(json.dumps([release("1.1.0")]).encode())
        report = r.check_releases("1.0.0", "stable", opener=opener)
        self.assertEqual(report["candidates"][0]["version"], "1.1.0")
        self.assertIn("/releases?per_page=100&page=1", requests[0].full_url)
        self.assertNotIn("Authorization", dict(requests[0].headers))

    def test_http_errors_are_ui_readable(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "denied", {}, None)
        with self.assertRaisesRegex(r.ReleaseError, "rate limited"):
            r.check_releases("1.0.0", "stable", opener=opener)

    def test_api_size_limit(self):
        with mock.patch.object(r, "MAX_API_BYTES", 10):
            with self.assertRaisesRegex(r.ReleaseError, "safety limit"):
                r.check_releases("1.0.0", "stable", opener=lambda *a, **kw: Response(b"x" * 11))

    def test_download_rejects_arbitrary_urls(self):
        for url in ["http://github.com/" + r.REPOSITORY + "/releases/download/x/y", "https://evil.example/a", "https://github.com.evil.example/a", "https://github.com/evil/repo/releases/download/v1/x"]:
            with self.assertRaises(r.ReleaseError):
                r.download_bundle(url, "never-written")

    def test_redirect_policy(self):
        handler = r._AssetRedirect()
        with self.assertRaisesRegex(r.ReleaseError, "untrusted"):
            handler.redirect_request(None, None, 302, "", {}, "http://release-assets.githubusercontent.com/file")
        self.assertTrue(r._safe_transfer_url("https://release-assets.githubusercontent.com/a?token=temporary"))
        self.assertFalse(r._safe_transfer_url("https://release-assets.githubusercontent.com.evil.example/a"))

    def test_bounded_download_and_partial_cleanup(self):
        url = release("1.0.0")["assets"][0]["browser_download_url"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            r.download_bundle(url, output, opener=lambda *a, **kw: Response(b"abc", url=url, length=3))
            self.assertEqual(output.read_bytes(), b"abc")
            output.unlink()
            with mock.patch.object(r, "MAX_ARCHIVE_BYTES", 2):
                with self.assertRaisesRegex(r.ReleaseError, "safety limit"):
                    r.download_bundle(url, output, opener=lambda *a, **kw: Response(b"abc", url=url))
            self.assertFalse(output.exists())

    def test_download_does_not_overwrite(self):
        url = release("1.0.0")["assets"][0]["browser_download_url"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            output.write_bytes(b"existing")
            with self.assertRaises(r.ReleaseError):
                r.download_bundle(url, output, opener=lambda *a, **kw: Response(b"abc", url=url))
            self.assertEqual(output.read_bytes(), b"existing")

    def test_download_connection_failure_removes_partial_file(self):
        url = release("1.0.0")["assets"][0]["browser_download_url"]
        class Broken(Response):
            def read(self, size=-1):
                if self.tell():
                    raise http.client.IncompleteRead(b"", 5)
                return super().read(size)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            with self.assertRaises(r.ReleaseError):
                r.download_bundle(url, output, opener=lambda *a, **kw: Broken(b"abc", url=url))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
