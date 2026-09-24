"""HTTP fetching with optional routing through a scraping/unblocker API.

realestate.com.au and property.com.au sit behind bot protection and answer
plain HTTP clients with HTTP 429. Set FETCH_URL_TEMPLATE (see .env.example) to
send requests through a scraping provider instead.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse

import httpx

from ..config import FetchSettings

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


class BlockedError(RuntimeError):
    """The site refused the request (bot protection / rate limit)."""


class Fetcher:
    def __init__(self, settings: FetchSettings):
        self.settings = settings
        self._client = httpx.Client(
            headers=_HEADERS, timeout=settings.timeout_seconds, follow_redirects=True
        )
        self._last_request = 0.0

    def get(self, url: str) -> str:
        wait = self.settings.delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        target = url
        if self.settings.url_template:
            target = self.settings.url_template.replace("{url}", urllib.parse.quote(url, safe=""))
        try:
            response = self._client.get(target)
        finally:
            self._last_request = time.monotonic()
        if response.status_code in (403, 429):
            raise BlockedError(
                f"{url} returned HTTP {response.status_code}. The site is blocking "
                "automated requests; set FETCH_URL_TEMPLATE to use a scraping provider."
            )
        response.raise_for_status()
        return response.text

    def close(self) -> None:
        self._client.close()


# --- helpers for pulling the JSON state these sites embed in their HTML ---

_SCRIPT_ASSIGN = re.compile(
    r"window\.(?:ArgonautExchange|__INITIAL_STATE__|__APOLLO_STATE__)\s*=\s*", re.S
)
_NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_JSON_LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _decode_nested(value):
    """Recursively decode JSON that is itself stored as a JSON string."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "{[" and len(stripped) > 1:
            try:
                return _decode_nested(json.loads(stripped))
            except ValueError:
                return value
        return value
    if isinstance(value, dict):
        return {k: _decode_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_nested(v) for v in value]
    return value


def embedded_json(html: str) -> list:
    """Every JSON blob embedded in the page, with nested JSON strings decoded."""
    blobs = []
    decoder = json.JSONDecoder()
    for match in _SCRIPT_ASSIGN.finditer(html):
        try:
            obj, _ = decoder.raw_decode(html, match.end())
            blobs.append(_decode_nested(obj))
        except ValueError:
            continue
    for pattern in (_NEXT_DATA, _JSON_LD):
        for raw in pattern.findall(html):
            try:
                blobs.append(_decode_nested(json.loads(raw)))
            except ValueError:
                continue
    return blobs


def walk(obj):
    """Yield every dict inside a JSON structure."""
    stack = [obj]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def dig(obj, *path, default=None):
    for key in path:
        if isinstance(obj, dict) and key in obj:
            obj = obj[key]
        elif isinstance(obj, list) and isinstance(key, int) and -len(obj) <= key < len(obj):
            obj = obj[key]
        else:
            return default
    return obj
