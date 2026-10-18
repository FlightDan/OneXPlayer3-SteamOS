"""Anonymous, bounded GitHub transport with fixed HTTPS proxy routes.

Routes are transport conveniences, never trust anchors. Callers must still verify
publisher signatures and signed hashes. Only public publisher repositories are
accepted; request credentials and arbitrary proxy addresses are never accepted.
"""
from __future__ import annotations

import io
import http.client
import os
import urllib.error
import urllib.parse
import urllib.request

NETWORK_MODES = ('auto', 'direct', 'gh-proxy.com', 'ghfast.top', 'ghproxy.net')
REPOSITORIES = ('FlightDan/OneXPlayer3-SteamOS', 'FlightDan/Opti2XMX')
PROXIES = NETWORK_MODES[2:]
CDN_HOSTS = frozenset(('release-assets.githubusercontent.com', 'objects.githubusercontent.com',
                       'github-releases.githubusercontent.com'))
MAX_REDIRECTS = 5


class NetworkError(urllib.error.URLError):
    """A safe route failed; no credentials or arbitrary URLs enter its message."""


def policy_options():
    """Stable UI values; availability describes evidence, not a future guarantee."""
    return [dict(id=mode, label=mode, tested='2026-10-18',
                 supports_api=mode in ('auto', 'direct', 'gh-proxy.com'),
                 supports_atom=mode in ('auto', 'direct')) for mode in NETWORK_MODES]


def mode_from_env(environ=None):
    value = (os.environ if environ is None else environ).get('OXP3_GITHUB_NETWORK', 'auto')
    if value not in NETWORK_MODES:
        raise ValueError('Unknown GitHub network route')
    return value


def _parts(url):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or '\\' in url:
        raise ValueError('Invalid public GitHub URL')
    value = urllib.parse.urlsplit(url)
    if (value.scheme != 'https' or value.port not in (None, 443)
            or value.username is not None or value.password is not None or value.fragment):
        raise ValueError('Only credential-free HTTPS URLs are allowed')
    return value


def resource_kind(url):
    value = _parts(url)
    if value.hostname == 'api.github.com':
        if value.path not in ('/repos/' + repo + '/releases' for repo in REPOSITORIES):
            raise ValueError('Unsupported public GitHub API request')
        query = urllib.parse.parse_qs(value.query, strict_parsing=True)
        if set(query) - {'per_page', 'page'} or any(len(v) != 1 or not v[0].isdigit() for v in query.values()):
            raise ValueError('Unsupported public GitHub API query')
        return 'api'
    if value.hostname == 'github.com' and not value.query:
        if value.path == '/FlightDan/OneXPlayer3-SteamOS/releases.atom':
            return 'atom'
        pieces = urllib.parse.unquote(value.path).split('/')
        if (len(pieces) == 7 and '/'.join(pieces[1:3]) in REPOSITORIES
                and pieces[3:5] == ['releases', 'download']
                and all(p and p not in ('.', '..') and not any(ord(c) < 33 for c in p) for p in pieces[1:])):
            return 'asset'
    raise ValueError('Only public publisher GitHub releases may use this transport')


def _transfer_allowed(url, original, route):
    try:
        value = _parts(url)
        if url == original:
            return True
        if route in PROXIES and url == 'https://' + route + '/' + original:
            return True
        if resource_kind(original) != 'asset':
            return False
        if value.hostname in CDN_HOSTS:
            return True
        return route in PROXIES and url == 'https://' + route + '/' + original
    except ValueError:
        return False


class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def __init__(self, original, route):
        self.original, self.route = original, route

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _transfer_allowed(newurl, self.original, self.route):
            raise NetworkError('GitHub route redirected outside allowed HTTPS locations')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class _Response:
    """Preserve canonical URL identity after validating every transport hop."""

    def __init__(self, response, original, prefix):
        self.response, self.original, self.prefix = response, original, io.BytesIO(prefix)
        self.headers = response.headers

    def read(self, size=-1):
        prefix = self.prefix.read(size)
        if size < 0:
            return prefix + self.response.read()
        return prefix + self.response.read(size - len(prefix)) if len(prefix) < size else prefix

    def geturl(self):
        return self.original

    def close(self):
        self.response.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class NetworkPolicy:
    def __init__(self, mode='auto', *, opener_factory=None):
        if mode not in NETWORK_MODES:
            raise ValueError('Unknown GitHub network route')
        self.mode = mode
        self._opener_factory = opener_factory or urllib.request.build_opener

    def routes(self, url):
        kind = resource_kind(url)
        if self.mode == 'direct':
            return ('direct',)
        if kind == 'atom':
            return ('direct',)
        if kind == 'api':
            return ('gh-proxy.com', 'direct') if self.mode == 'gh-proxy.com' else ('direct', 'gh-proxy.com')
        if self.mode == 'auto':
            return ('direct', *PROXIES)
        return (self.mode, 'direct', *(p for p in PROXIES if p != self.mode))

    def open(self, request, timeout=30):
        if isinstance(request, str):
            request = urllib.request.Request(request)
        original = request.full_url
        kind = resource_kind(original)
        if request.get_method() != 'GET' or request.data is not None:
            raise ValueError('Only anonymous public GET requests are supported')
        headers = dict(request.header_items())
        if any(name.lower() not in {'user-agent', 'accept', 'x-github-api-version', 'range'} for name in headers):
            raise ValueError('Credentials and custom headers cannot be sent to GitHub routes')
        last = None
        for route in self.routes(original):
            routed = original if route == 'direct' else 'https://' + route + '/' + original
            response = None
            try:
                opener = self._opener_factory(_Redirect(original, route))
                response = opener.open(urllib.request.Request(routed, headers=headers), timeout=min(timeout, 15))
                final = response.geturl()
                if not _transfer_allowed(final, original, route):
                    raise NetworkError('GitHub route ended outside allowed HTTPS locations')
                if getattr(response, 'status', 200) != 200:
                    raise NetworkError('GitHub route returned an unexpected partial response')
                prefix = response.read(512)
                content_type = response.headers.get('Content-Type', '').lower()
                stripped = prefix.lstrip().lower()
                if ('text/html' in content_type or stripped.startswith((b'<!doctype html', b'<html'))
                        or not prefix or kind == 'api' and not stripped.startswith(b'[')
                        or kind == 'atom' and not stripped.startswith((b'<?xml', b'<feed'))):
                    raise NetworkError('GitHub route returned an invalid resource')
                return _Response(response, original, prefix)
            except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as error:
                last = error
                if response is not None:
                    response.close()
                if isinstance(error, urllib.error.HTTPError):
                    error.close()
        if isinstance(last, urllib.error.HTTPError):
            raise last
        raise NetworkError('All selected GitHub routes failed') from last
