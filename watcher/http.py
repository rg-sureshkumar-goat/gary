"""Tiny stdlib HTTP helper. No third-party deps so the job never breaks on install."""
import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}


# Bot tokens and API keys ride in URLs. Error messages end up in CI logs, and
# for a public repo those logs are world-readable, so redact before raising.
_SECRET_IN_URL = re.compile(r"(/bot)\d{6,}:[A-Za-z0-9_-]{20,}", re.I)
_QUERY_SECRET = re.compile(r"([?&](?:token|key|api_key|access_token)=)[^&\s]+", re.I)


def redact(text):
    text = _SECRET_IN_URL.sub(r"\1<REDACTED>", str(text or ""))
    return _QUERY_SECRET.sub(r"\1<REDACTED>", text)


class HttpError(Exception):
    def __init__(self, status, url, body=""):
        super().__init__("HTTP %s for %s" % (status, redact(url)))
        self.status = status
        self.url = redact(url)
        self.body = body


def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def fetch(url, method="GET", payload=None, headers=None, timeout=30, retries=2):
    """Return the decoded body of a request. Retries transient failures."""
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _read(resp)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = _read(exc)
            except Exception:
                pass
            last = HttpError(exc.code, url, body)
            # 4xx other than rate-limiting means the endpoint is wrong; don't retry.
            if 400 <= exc.code < 500 and exc.code not in (408, 425, 429):
                raise last
        except Exception as exc:  # timeouts, DNS, TLS, connection resets
            last = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last


def fetch_json(url, method="GET", payload=None, headers=None, timeout=30, retries=2):
    body = fetch(url, method, payload, headers, timeout, retries)
    return json.loads(body)
