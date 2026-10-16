"""Public GitHub release discovery; no tokens or GitHub 'latest' endpoint.

``check_releases`` returns repository, installed_version, channel, candidates.
Candidates are descending SemVer dictionaries containing version, display_version,
channel, tag_name, notes, published_at, asset_name, download_url, and size.
"""
from __future__ import annotations

from functools import total_ordering
import errno
import http.client
import json
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .bundle import MAX_ARCHIVE_BYTES

REPOSITORY = "FlightDan/OneXPlayer3-SteamOS"
API_URL = "https://api.github.com/repos/" + REPOSITORY + "/releases"
MAX_API_BYTES = 8 * 1024 * 1024
ATOM_URL = 'https://github.com/' + REPOSITORY + '/releases.atom'
MAX_FEED_BYTES = 2 * 1024 * 1024
REQUEST_ATTEMPTS = 2
REQUEST_TIMEOUT = 30
RETRY_DELAY = 0.5
_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z")


class ReleaseError(Exception):
    """A release service error suitable for showing in the maintenance UI."""

    def __init__(self, message, *, http_status=None, code='release_error', retryable=False):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.retryable = retryable


@total_ordering
class _Version:
    def __init__(self, value):
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError("Invalid SemVer")
        self.text = value[1:] if value.startswith("v") else value
        match = _PATTERN.fullmatch(self.text)
        if not match:
            raise ValueError("Invalid SemVer")
        self.core = tuple(int(n) for n in match.groups()[:3])
        self.pre = tuple(match.group(4).split(".")) if match.group(4) else ()
        if any(p.isdigit() and len(p) > 1 and p.startswith("0") for p in self.pre):
            raise ValueError("Invalid SemVer prerelease")

    def __eq__(self, other):
        return isinstance(other, _Version) and (self.core, self.pre) == (other.core, other.pre)

    def __lt__(self, other):
        if self.core != other.core:
            return self.core < other.core
        if not self.pre or not other.pre:
            return bool(self.pre) and not bool(other.pre)
        for left, right in zip(self.pre, other.pre):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.pre) < len(other.pre)


def _tag_version(value):
    """Maintenance releases have their own tag namespace; versions stay SemVer."""
    if isinstance(value, str) and value.startswith('maintenance-v'):
        value = value[len('maintenance-'):]
    return _Version(value)


def _asset_url(url, *, catalog=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        parts = urllib.parse.unquote(parsed.path).split("/")
        if len(parts) != 7 or any(p in ("", ".", "..") for p in parts[1:]):
            return False
        tag_version = _tag_version(parts[5])
        prefix = "oxp3-maintenance-%s" % tag_version.text
        filenames = {prefix + '-linux-x86_64.tar.gz'}
        if catalog:
            filenames |= {prefix + '-catalog.json', prefix + '-catalog.sig'}
        return (parsed.scheme == "https" and parsed.hostname == "github.com"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and "/".join(parts[1:5]) == REPOSITORY + "/releases/download"
                and parts[6] in filenames)
    except (ValueError, TypeError, AttributeError):
        return False


def _safe_transfer_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        return (parsed.scheme == "https" and parsed.port in (None, 443)
                and not parsed.username and not parsed.password and not parsed.fragment
                and (parsed.hostname in {"release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"}
                     or _asset_url(url, catalog=True)))
    except (ValueError, TypeError):
        return False


class _AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _safe_transfer_url(newurl):
            raise ReleaseError("GitHub redirected the download to an untrusted location.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ReleaseError("The GitHub releases service redirected unexpectedly.")


def _connection_error(exc):
    """Stable error codes let native UIs localize without parsing English."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (403, 429):
            return ReleaseError('GitHub release requests are temporarily rate limited. Try again later.',
                                http_status=exc.code, code='rate_limited')
        if exc.code == 404:
            return ReleaseError('The project release or bundle is unavailable on GitHub.',
                                http_status=404, code='release_unavailable')
        transient = exc.code in (408, 500, 502, 503, 504)
        return ReleaseError('GitHub returned HTTP %s. Try again later.' % exc.code,
                            http_status=exc.code, code='github_unavailable' if transient else 'http_error', retryable=transient)
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (ssl.SSLCertVerificationError, ssl.CertificateError)):
        return ReleaseError('GitHub HTTPS certificate verification failed. Check your system clock and network settings.',
                            code='tls_verification_failed')
    transient = (isinstance(exc, urllib.error.URLError)
                 or isinstance(reason, (TimeoutError, ConnectionError, http.client.HTTPException))
                 or isinstance(reason, OSError) and reason.errno in {
                     errno.EAGAIN, errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
                     errno.ENETDOWN, errno.ENETRESET, errno.ENETUNREACH, errno.EPIPE, errno.ETIMEDOUT,
                     errno.EHOSTUNREACH})
    return ReleaseError('Could not contact GitHub. Check your connection and try again.',
                        code='network_unavailable', retryable=transient)


def _request(url, opener=None, *, download=False, progress=None):
    """Retry connection establishment only, never authentication failures.

    At most two 30-second attempts and one short backoff. Stream read errors
    remain explicit failures; archive callers clean partial downloads safely.
    Progress callbacks run on the caller's worker thread and contain no URLs.
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": "OXP3-Maintenance/1", "Accept": "application/octet-stream" if download else "application/atom+xml" if url == ATOM_URL else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    if opener is None:
        opener = urllib.request.build_opener(_AssetRedirect() if download else _NoRedirect()).open
    elif hasattr(opener, "open"):
        opener = opener.open
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        if progress:
            progress({'phase': 'contacting_github', 'attempt': attempt, 'attempts': REQUEST_ATTEMPTS})
        try:
            return opener(request, timeout=REQUEST_TIMEOUT)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            error = _connection_error(exc)
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if not error.retryable or attempt == REQUEST_ATTEMPTS:
                raise error from exc
            if progress:
                progress({'phase': 'retrying_github', 'attempt': attempt + 1, 'attempts': REQUEST_ATTEMPTS})
            time.sleep(RETRY_DELAY)


def release_candidates(releases: list, installed_version: str, channel: str, *, include_current=False) -> list:
    """Select newer releases with this project's exact maintenance asset.

    Stable accepts stable versions. Beta accepts stable and ``-beta`` versions.
    SemVer build metadata never makes an otherwise equal release newer.
    """
    if channel not in ("stable", "beta"):
        raise ReleaseError("Update channel must be stable or beta.")
    try:
        installed = _Version(installed_version)
    except ValueError as exc:
        raise ReleaseError("Installed version is not valid semantic version metadata.") from exc
    if not isinstance(releases, list):
        raise ReleaseError("GitHub returned an invalid release list.")
    result, seen = [], set()
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        try:
            version = _tag_version(release.get("tag_name"))
        except ValueError:
            continue
        if version < installed or version == installed and not include_current:
            continue
        is_beta = bool(version.pre)
        if is_beta and (channel != "beta" or version.pre[0] != "beta"):
            continue
        if not is_beta and release.get("prerelease"):
            continue
        expected = "oxp3-maintenance-%s-linux-x86_64.tar.gz" % version.text
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") != expected:
                continue
            url, size = asset.get("browser_download_url"), asset.get("size")
            if not _asset_url(url) or type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
                continue
            if urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[1]) != expected:
                continue
            if version.text in seen:
                break
            seen.add(version.text)
            catalog_assets = {}
            for extra in assets:
                if not isinstance(extra, dict):
                    continue
                for suffix in ('json', 'sig'):
                    if (extra.get('name') == 'oxp3-maintenance-' + version.text + '-catalog.' + suffix
                            and _asset_url(extra.get('browser_download_url'), catalog=True)
                            and type(extra.get('size')) is int and 0 < extra['size'] <= (1024 * 1024 if suffix == 'json' else 256)):
                        catalog_assets[suffix] = extra['browser_download_url']
            result.append((version, {
                "version": version.text, "display_version": str(release.get("name") or version.text)[:512],
                "channel": "beta" if is_beta else "stable", "tag_name": release["tag_name"],
                "notes": str(release.get("body") or "")[:256 * 1024],
                "published_at": str(release.get("published_at") or "")[:64],
                "asset_name": expected, "download_url": url, "size": size,
                "catalog_urls": catalog_assets if set(catalog_assets) == {'json', 'sig'} else {}}))
            break
    result.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in result]


def _feed_projects(raw, channel):
    """Read advisory project tags; Atom never proves package availability."""
    if len(raw) > MAX_FEED_BYTES:
        raise ReleaseError('GitHub release feed exceeds the safety limit.')
    try:
        text = raw.decode('utf-8-sig')
        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I) or '\x00' in text:
            raise ValueError('XML declarations are unsupported')
        feed = ET.fromstring(text)
        ns = '{http://www.w3.org/2005/Atom}'
        if feed.tag != ns + 'feed':
            raise ValueError('Not an Atom feed')
        entries = feed.findall(ns + 'entry')
        if len(entries) > 1000:
            raise ValueError('Too many feed entries')
        projects, seen = [], set()
        prefix = 'https://github.com/' + REPOSITORY + '/releases/tag/'
        for entry in entries:
            links = [item.get('href', '') for item in entry.findall(ns + 'link')
                     if item.get('rel', 'alternate') == 'alternate']
            if len(links) != 1 or not links[0].startswith(prefix):
                continue
            # GitHub Atom links encode SemVer's build separator as %2B. Decode
            # only that character; all other encoded aliases remain invalid.
            tag = re.sub(r'%2[bB]', '+', links[0][len(prefix):])
            try:
                version = _tag_version(tag)
            except ValueError:
                continue
            # The literal repository prefix and SemVer tag reject other origins,
            # path separators, URL suffixes and other percent-encoded aliases.
            if tag in seen:
                continue
            if version.pre and (channel != 'beta' or version.pre[0] != 'beta'):
                continue
            seen.add(tag)
            title = entry.findtext(ns + 'title') or version.text
            projects.append((version, {'version': version.text,
                'display_version': title[:512], 'tag_name': tag,
                'channel': 'beta' if version.pre else 'stable',
                'notes': (entry.findtext(ns + 'content') or '')[:256 * 1024],
                'published_at': (entry.findtext(ns + 'updated') or '')[:64],
                'release_url': links[0], 'advisory': True}))
        projects.sort(key=lambda item: (item[0], item[1]['tag_name'].startswith('maintenance-v')), reverse=True)
        return [item[1] for item in projects]
    except (ValueError, UnicodeError, ET.ParseError, RecursionError) as error:
        raise ReleaseError('GitHub returned an unreadable release feed.') from error


def _check_feed(installed_version, channel, *, opener=None, public_key=None, progress=None, api_error=None):
    from .bundle import BundleError
    with _request(ATOM_URL, opener, progress=progress) as response:
        final = response.geturl() if hasattr(response, 'geturl') else ATOM_URL
        if final is not None and final != ATOM_URL:
            raise ReleaseError('The GitHub release feed redirected unexpectedly.')
        projects = _feed_projects(response.read(MAX_FEED_BYTES + 1), channel)
    latest = projects[0] if projects else None
    transient_api = api_error is not None and api_error.code in ('network_unavailable', 'github_unavailable')
    warnings = [('GitHub API unavailable' if transient_api else 'GitHub API rate limited')
                + '; project versions came from the public Atom feed and are advisory.']
    available, unknown = [], False
    key = Path(public_key) if public_key is not None else Path(__file__).resolve().parent.parent / 'trusted-public-key.pem'
    if not key.is_file() or key.is_symlink():
        unknown = True
        warnings.append('Installed signing key is unavailable; maintenance package availability could not be authenticated.')
    else:
        for project in projects[:3]:
            version, tag = project['version'], project['tag_name']
            base = 'https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/'
            urls = {suffix: base + 'oxp3-maintenance-' + version + '-catalog.' + suffix for suffix in ('json', 'sig')}
            try:
                catalog = fetch_catalog({'version': version, 'catalog_urls': urls}, key, opener=opener, progress=progress)
                # fetch_catalog binds the signature and schema to this tag's
                # version. Only that authenticated catalog establishes a bundle.
                bundle, release = catalog['bundle'], catalog['release']
                url = base + bundle['name']
                if not _asset_url(url):
                    raise BundleError('Signed catalog bundle location is invalid')
                available.append(dict(project, display_version=release.get('display_version', version),
                    asset_name=bundle['name'], download_url=url, size=bundle['size'],
                    catalog_urls=urls, catalog_verified=True))
            except ReleaseError as error:
                if error.http_status == 404:
                    warnings.append('No signed maintenance catalog is published for ' + version + '.')
                else:
                    unknown = True
                    warnings.append('Could not authenticate maintenance availability for ' + version + ': ' + str(error))
            except BundleError as error:
                unknown = True
                warnings.append('Signed maintenance catalog verification failed for ' + version + ': ' + str(error))
    installed = _Version(installed_version)
    candidates = [item for item in available if _Version(item['version']) > installed]
    latest_bundle = available[0] if available else None
    status = ('maintenance_availability_unknown' if unknown else
              'maintenance_package_pending' if latest and (not latest_bundle or _Version(latest['version']) > _Version(latest_bundle['version'])) else
              'update_available' if candidates else 'up_to_date' if latest_bundle else 'no_releases')
    return {'repository': REPOSITORY, 'installed_version': installed_version, 'channel': channel,
            'candidates': candidates, 'latest_project': latest, 'maintenance_releases': available,
            'latest_maintenance': latest_bundle, 'status': status,
            'discovery_source': 'github_atom', 'api_error_code': api_error.code if api_error else 'rate_limited',
            'warning': ' '.join(warnings)}


def check_releases(installed_version: str, channel: str, *, opener=None, public_key=None, progress=None) -> dict:
    """Read bounded paginated public releases and return the candidate report."""
    release_candidates([], installed_version, channel)
    releases = []
    try:
        for page in range(1, 11):
            with _request(API_URL + "?per_page=100&page=" + str(page), opener, progress=progress) as response:
                raw = response.read(MAX_API_BYTES + 1)
            if len(raw) > MAX_API_BYTES:
                raise ReleaseError("GitHub release data exceeds the safety limit.")
            entries = json.loads(raw)
            if not isinstance(entries, list) or len(entries) > 100:
                raise ReleaseError("GitHub returned an invalid release list.")
            releases.extend(entries)
            if len(entries) < 100:
                break
        # Latest project metadata is useful even when a Windows-only release has
        # not yet shipped a maintenance bundle. Never report that as up to date.
        project = []
        for item in releases:
            if not isinstance(item, dict) or item.get('draft'):
                continue
            try:
                version = _tag_version(item.get('tag_name'))
            except ValueError:
                continue
            if version.pre and (channel != 'beta' or version.pre[0] != 'beta'):
                continue
            if not version.pre and item.get('prerelease'):
                continue
            project.append((version, {'version': version.text, 'display_version': str(item.get('name') or version.text)[:512],
                                      'notes': str(item.get('body') or '')[:256 * 1024]}))
        project.sort(key=lambda item: item[0], reverse=True)
        latest = project[0][1] if project else None
        available = release_candidates(releases, '0.0.0', channel, include_current=True)
        candidates = release_candidates(releases, installed_version, channel)
        latest_bundle = available[0] if available else None
        return {"repository": REPOSITORY, "installed_version": installed_version, "channel": channel,
                "candidates": candidates, 'latest_project': latest, 'maintenance_releases': available,
                'latest_maintenance': latest_bundle,
                'status': ('maintenance_package_pending' if latest and (not latest_bundle or _Version(latest['version']) > _Version(latest_bundle['version']))
                           else 'update_available' if candidates else 'up_to_date' if latest_bundle else 'no_releases')}
    except ReleaseError as error:
        if (error.http_status in (403, 429)
                or error.retryable and error.code in ('network_unavailable', 'github_unavailable')):
            try:
                return _check_feed(installed_version, channel, opener=opener, public_key=public_key,
                                   progress=progress, api_error=error)
            except (ReleaseError, OSError, ValueError, http.client.HTTPException):
                pass
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ReleaseError("GitHub returned unreadable release data.") from exc
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ReleaseError("Reading GitHub release data failed. Try again later.",
                           code='network_read_failed', retryable=True) from exc


def download_bundle(url, destination, *, opener=None, progress=None) -> Path:
    """Stream a bounded project release asset into a new destination file.

    Discovery metadata and HTTPS are not authenticity proofs. Call inspect_bundle
    or verify_bundle with the installed trust anchor before using downloaded data.
    """
    if not _asset_url(url):
        raise ReleaseError("Only maintenance assets from the configured project may be downloaded.")
    destination = Path(destination)
    created = False
    try:
        with _request(url, opener, download=True, progress=progress) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if not _safe_transfer_url(final_url):
                raise ReleaseError("The bundle download came from an untrusted location.")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_ARCHIVE_BYTES):
                raise ReleaseError("The bundle download exceeds the safety limit.")
            with destination.open("xb") as output:
                created = True
                total = 0
                while True:
                    data = response.read(1024 * 1024)
                    if not data:
                        break
                    total += len(data)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ReleaseError("The bundle download exceeds the safety limit.")
                    output.write(data)
                if total == 0 or (length is not None and total != int(length)):
                    raise ReleaseError("The bundle download is empty or incomplete.")
        return destination
    except (ReleaseError, OSError, TimeoutError, http.client.HTTPException) as exc:
        if created:
            destination.unlink(missing_ok=True)
        if isinstance(exc, ReleaseError):
            raise
        raise ReleaseError("Could not save the bundle download: %s" % exc, code='download_failed') from exc


def fetch_catalog(candidate, key, *, opener=None, openssl='openssl', progress=None):
    """Fetch a small signed index before asking for a full payload download."""
    from .catalog import verify, MAX_CATALOG_BYTES
    urls = candidate.get('catalog_urls', {})
    if set(urls) != {'json', 'sig'}:
        raise ReleaseError('This release has no signed capability catalog; import its full signed bundle instead.')
    data = {}
    for suffix, limit in (('json', MAX_CATALOG_BYTES), ('sig', 256)):
        url = urls[suffix]
        expected = 'oxp3-maintenance-' + candidate['version'] + '-catalog.' + suffix
        if not _asset_url(url, catalog=True) or urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/', 1)[1]) != expected:
            raise ReleaseError('Invalid capability catalog location')
        try:
            with _request(url, opener, download=True, progress=progress) as response:
                final = response.geturl() if hasattr(response, 'geturl') else url
                if not _safe_transfer_url(final):
                    raise ReleaseError('Untrusted capability catalog redirect')
                data[suffix] = response.read(limit + 1)
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise ReleaseError('Reading the GitHub capability catalog failed. Try again later.',
                               code='network_read_failed', retryable=True) from exc
        if len(data[suffix]) > limit:
            raise ReleaseError('Capability catalog exceeds the size limit')
    return verify(data['json'], data['sig'], key, expected_version=candidate['version'], openssl=openssl)
