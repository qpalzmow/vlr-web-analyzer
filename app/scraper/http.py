import time
import random
import urllib.parse as urlparse
import httpx
from app.config import ALLOWED_VLR_HOSTS, USER_AGENTS

_shared_client: httpx.Client = None

def get_httpx_client() -> httpx.Client:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
    return _shared_client

def close_httpx_client():
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        _shared_client.close()
        _shared_client = None

def validate_vlr_url(url: str) -> str:
    """SSRF Protection: Ensure URL uses HTTPS and points strictly to an allowed VLR domain."""
    if not url:
        raise ValueError("URL cannot be empty")
    parsed = urlparse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    if parsed.hostname not in ALLOWED_VLR_HOSTS:
        raise ValueError(f"Host '{parsed.hostname}' is not in allowed VLR domain allowlist")
    return url

def _get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept-Language': 'en-US,en;q=0.9',
    }

def request_with_retry(url: str, max_retries: int = 3) -> httpx.Response:
    """HTTP GET via shared httpx client with SSRF validation, retry, and exponential backoff."""
    validate_vlr_url(url)
    client = get_httpx_client()
    last_err = None

    for attempt in range(max_retries):
        try:
            res = client.get(url, headers=_get_headers())
            if res.status_code == 200:
                return res
            if res.status_code in (301, 302, 307, 308):
                location = res.headers.get("Location")
                if location:
                    redirect_url = urlparse.urljoin(url, location)
                    validate_vlr_url(redirect_url)
                    return client.get(redirect_url, headers=_get_headers())
                return res
            if res.status_code == 404:
                raise httpx.HTTPStatusError(f"404 Not Found: {url}", request=res.request, response=res)
            if res.status_code in (429, 502, 503, 504):
                last_err = Exception(f"Status {res.status_code}")
                retry_after = res.headers.get('Retry-After')
                if retry_after and retry_after.isdigit():
                    wait = min(int(retry_after), 60)
                else:
                    wait = min(30, 2 ** attempt + random.uniform(0.1, 1.0))
                time.sleep(wait)
                continue
            return res
        except httpx.HTTPStatusError:
            raise
        except Exception as e:
            last_err = e
            wait = min(30, 2 ** attempt + random.uniform(0.1, 1.0))
            time.sleep(wait)

    raise last_err if last_err else Exception(f"Request failed for {url}")
