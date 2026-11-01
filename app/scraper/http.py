import time
import random
import threading
import os
import urllib.parse as urlparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from app.config import ALLOWED_VLR_HOSTS, USER_AGENTS

_shared_client: httpx.Client = None
_client_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_request_at = 0.0
_cooldown_until = 0.0
_collection_deadline = None


class CollectionBudgetExceeded(RuntimeError):
    """Stop starting source requests; completed data can still be checkpointed."""


def set_collection_deadline(seconds):
    global _collection_deadline
    with _rate_lock:
        _collection_deadline = None if seconds is None else time.monotonic() + seconds


def remaining_collection_seconds():
    """Read the shared deadline, including from collector executor threads."""
    with _rate_lock:
        deadline = _collection_deadline
    return None if deadline is None else max(0.0, deadline - time.monotonic())


def check_collection_budget():
    remaining = remaining_collection_seconds()
    if remaining is not None and remaining <= 0:
        raise CollectionBudgetExceeded('Source collection time budget reached')
    return remaining


def _request_timeout():
    # HTTPX timeouts bound each I/O operation, not total response duration.
    # The collector supervisor separately bounds the whole process.
    remaining = check_collection_budget()
    return httpx.Timeout(15.0 if remaining is None else min(15.0, remaining),
                         connect=5.0 if remaining is None else min(5.0, remaining))


def _wait_for_request():
    global _next_request_at
    interval = max(0.0, float(os.environ.get('VLR_REQUEST_INTERVAL_SECONDS', '0')))
    while True:
        with _rate_lock:
            now = time.monotonic()
            wait = max(0.0, _next_request_at - now, _cooldown_until - now)
            if _collection_deadline is not None and now + wait >= _collection_deadline:
                raise CollectionBudgetExceeded('Source collection time budget reached')
            if wait == 0:
                _next_request_at = now + interval
                return
        time.sleep(wait)


def _rate_limit_wait(response):
    value = response.headers.get('Retry-After', '')
    try:
        wait = float(value)
    except ValueError:
        try:
            wait = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            wait = 30
    return max(1.0, min(wait, 300.0))


def _defer_all_requests(seconds):
    global _cooldown_until
    with _rate_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


def _retry_sleep(seconds):
    remaining = check_collection_budget()
    if remaining is not None and seconds >= remaining:
        raise CollectionBudgetExceeded('Source collection time budget reached')
    time.sleep(seconds)
    check_collection_budget()

def get_httpx_client() -> httpx.Client:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        with _client_lock:
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.Client(
                    follow_redirects=False,
                    timeout=httpx.Timeout(15.0, connect=5.0),
                    limits=httpx.Limits(max_keepalive_connections=15, max_connections=30)
                )
    return _shared_client

def close_httpx_client():
    global _shared_client
    with _client_lock:
        if _shared_client is not None and not _shared_client.is_closed:
            _shared_client.close()
            _shared_client = None

def validate_vlr_url(url: str) -> str:
    """SSRF Protection & Normalizer: Ensure URL points strictly to allowed VLR domain or valid path."""
    if not url or str(url).strip() in ("", "undefined", "null", "None"):
        raise ValueError("URL cannot be empty or undefined")
    url = str(url).strip()
    if url.isdigit():
        url = f"https://www.vlr.gg/{url}"
    elif url.startswith("/"):
        url = f"https://www.vlr.gg{url}"
    elif url.startswith("http://"):
        url = "https://" + url[7:]
    elif not url.startswith("https://"):
        url = f"https://{url}"

    parsed = urlparse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Invalid URL scheme: '{parsed.scheme}'. HTTPS is strictly required.")
    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_VLR_HOSTS:
        raise ValueError(f"Host '{hostname}' is not in allowed VLR domain allowlist")
    return url

def _get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept-Language': 'en-US,en;q=0.9',
    }

def request_with_retry(url: str, max_retries: int = 3) -> httpx.Response:
    """HTTP GET via shared httpx client with SSRF validation, retry, and exponential backoff."""
    url = validate_vlr_url(url)
    client = get_httpx_client()
    last_err = None

    for attempt in range(max_retries):
        _wait_for_request()
        try:
            res = client.get(url, headers=_get_headers(), timeout=_request_timeout())
            if res.status_code == 429:
                # Preserve the server's limit even if this response spent the
                # last collection seconds. Clearing a deadline is not a reset.
                _defer_all_requests(_rate_limit_wait(res))
            # An I/O timeout is per operation; a response can finish after the
            # cooperative deadline, including a redirect with a slow body.
            check_collection_budget()
            if res.status_code == 200:
                return res
            if res.status_code in (301, 302, 307, 308):
                location = res.headers.get("Location")
                if location:
                    redirect_url = urlparse.urljoin(url, location)
                    validate_vlr_url(redirect_url)
                    url = redirect_url
                    continue
                return res
            if res.status_code == 404:
                raise httpx.HTTPStatusError(f"404 Not Found: {url}", request=res.request, response=res)
            if res.status_code == 429:
                # One worker being limited must pause every collector worker.
                last_err = httpx.HTTPStatusError('VLR request rate limited', request=res.request, response=res)
                continue
            if res.status_code in (502, 503, 504):
                last_err = httpx.HTTPStatusError(f"VLR returned HTTP {res.status_code}",
                                                 request=res.request, response=res)
                retry_after = res.headers.get('Retry-After')
                if retry_after and retry_after.isdigit():
                    wait = min(int(retry_after), 60)
                else:
                    wait = min(30, 2 ** attempt + random.uniform(0.1, 1.0))
                _retry_sleep(wait)
                continue
            return res
        except CollectionBudgetExceeded:
            raise
        except httpx.HTTPStatusError:
            check_collection_budget()
            raise
        except Exception as e:
            check_collection_budget()
            last_err = e
            wait = min(30, 2 ** attempt + random.uniform(0.1, 1.0))
            _retry_sleep(wait)

    check_collection_budget()
    raise last_err if last_err else Exception(f"Request failed for {url}")
