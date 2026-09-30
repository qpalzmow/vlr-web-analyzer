"""Bounded, same-origin copies of known public team logos for report export."""
from functools import lru_cache
import re
import time
from urllib.parse import urlparse
import httpx


def validate_logo_url(url):
    parsed = urlparse(url or '')
    if (parsed.scheme != 'https' or parsed.netloc != 'owcdn.net' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/img/[A-Za-z0-9_-]+\.(?:png|jpe?g|webp|gif)', parsed.path, re.I)):
        raise ValueError('Unrecognized team logo')
    return url


@lru_cache(maxsize=128)
def _download(url, day):
    validate_logo_url(url)
    with httpx.Client(timeout=8, follow_redirects=False) as client:
        with client.stream('GET', url) as response:
            response.raise_for_status()
            mime = response.headers.get('content-type', '').split(';')[0]
            if mime not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
                raise ValueError('Unrecognized logo format')
            body = bytearray()
            for part in response.iter_bytes():
                body.extend(part)
                if len(body) > 256 * 1024:
                    raise ValueError('Logo exceeds size limit')
    return bytes(body), mime


def team_logo(url):
    return _download(validate_logo_url(url), int(time.time() // 86400))
