"""Live website check - the mandatory core of the pipeline.

The OSM `website` tag is a hint, never a fact (measured ~44% precision as a
naive "no website" signal). Every gap LeadShoot reports as verified comes from
actually fetching the site: working / broken / no_ssl, plus mobile-viewport
and booking-page scans of the HTML.

Politeness: robots.txt honored per host, bounded concurrency, one homepage
GET per business, honest User-Agent.
"""

from __future__ import annotations

import asyncio
import re
import ssl
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 LeadShoot/0.1"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
}
ROBOTS_UA = "LeadShoot"
HTML_SCAN_BYTES = 200_000
BOOKING_KEYWORDS = (
    "book now", "book online", "book an appointment", "appointment",
    "reserve", "reservation", "order online", "schedule online", "booking",
)

# statuses
WORKING = "working"
BROKEN = "broken"
NO_SSL = "no_ssl"
BLOCKED = "blocked"       # robots.txt disallows us - we do not judge the site
PROTECTED = "protected"   # WAF/bot defense (403 etc.) - site is alive, no gap
UNREACHABLE = "unreachable"  # DNS resolves but no connection - maybe a block
NO_SITE = "no_site_listed"

BOT_DEFENSE_CODES = {401, 403, 405, 406, 429}


SLOW_SECONDS = 4.0

# DIY site builders whose templates are a natural redesign/upgrade pitch.
# Shopify deliberately excluded: a working store is not a gap.
DIY_BUILDERS = {"wix", "squarespace", "godaddy", "weebly", "jimdo", "duda"}

_GENERATOR_RE = re.compile(
    r'name=["\']generator["\'][^>]*content=["\']([^"\']+)', re.I)
_WP_VERSION_RE = re.compile(r"wordpress\s+(\d+)", re.I)

_BUILDER_MARKERS = (
    ("wixstatic.com", "wix"), ("parastorage.com", "wix"),
    ("squarespace", "squarespace"),
    ("wsimg.com", "godaddy"),
    ("weebly.com", "weebly"), ("jimdo", "jimdo"), ("dudaone", "duda"),
    ("cdn.shopify.com", "shopify"),
    ("wp-content", "wordpress"), ("wp-includes", "wordpress"),
)


def detect_builder(lowered_html: str) -> tuple[str | None, int]:
    """(builder name, outdated 0/1) from homepage HTML we already fetched."""
    builder = None
    outdated = 0
    m = _GENERATOR_RE.search(lowered_html)
    generator = m.group(1) if m else ""
    if generator:
        g = generator.lower()
        for name in ("wordpress", "wix", "squarespace", "joomla", "drupal",
                     "weebly", "jimdo", "duda", "shopify"):
            if name in g:
                builder = name
                break
        wp = _WP_VERSION_RE.search(generator)
        if wp and int(wp.group(1)) < 6:
            outdated = 1
        if "joomla! 3" in g or "drupal 7" in g:
            outdated = 1
    if builder is None:
        for marker, name in _BUILDER_MARKERS:
            if marker in lowered_html:
                builder = name
                break
    return builder, outdated


@dataclass
class CheckResult:
    status: str
    http_code: int | None = None
    is_mobile: int | None = None
    has_booking: int | None = None
    builder: str | None = None
    outdated: int = 0
    slow: int = 0


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url


def root_of(url: str) -> str | None:
    """Site root for a deep link; None when the URL already is the root.

    A dead deep link with a living homepage is a stale listing, not a broken
    website - the checker retries the root before flagging broken_site.
    """
    parts = urlsplit(normalize_url(url))
    if parts.path in ("", "/") and not parts.query:
        return None
    return f"{parts.scheme}://{parts.netloc}/"


def scan_html(html: str) -> tuple[int, int]:
    """(is_mobile, has_booking) from the homepage HTML."""
    lowered = html[:HTML_SCAN_BYTES].lower()
    is_mobile = 1 if 'name="viewport"' in lowered or "name='viewport'" in lowered else 0
    has_booking = 1 if any(k in lowered for k in BOOKING_KEYWORDS) else 0
    return is_mobile, has_booking


def _full_scan(resp) -> dict:
    """Everything we learn from one successful homepage response."""
    lowered = resp.text[:HTML_SCAN_BYTES].lower()
    is_mobile, has_booking = scan_html(resp.text)
    builder, outdated = detect_builder(lowered)
    try:
        slow = 1 if resp.elapsed.total_seconds() > SLOW_SECONDS else 0
    except Exception:
        slow = 0
    return {"is_mobile": is_mobile, "has_booking": has_booking,
            "builder": builder, "outdated": outdated, "slow": slow}


def classify_code(code: int) -> str:
    if code < 400:
        return WORKING
    if code in BOT_DEFENSE_CODES:
        return PROTECTED  # a WAF answering means the site is up
    return BROKEN


def dns_resolves(host: str) -> bool:
    import socket

    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


async def robots_allows(client: httpx.AsyncClient, url: str,
                        cache: dict[str, urllib.robotparser.RobotFileParser | None]) -> bool:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = await client.get(f"{base}/robots.txt", timeout=6)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                cache[base] = rp
            else:
                cache[base] = None
        except Exception:
            cache[base] = None
    rp = cache[base]
    return True if rp is None else rp.can_fetch(ROBOTS_UA, url)


async def check_url(client: httpx.AsyncClient, url: str,
                    robots_cache: dict, _root_retry: bool = True) -> CheckResult:
    """Fetch one site: HTTPS first (validated), HTTP fallback => no_ssl.

    A 4xx on a deep link retries the site root once - stale paths in map
    data must not condemn a working website.
    """
    target = normalize_url(url)
    bare = target.split("://", 1)[1]

    if not await robots_allows(client, target, robots_cache):
        return CheckResult(status=BLOCKED)

    def _dead_or_unreachable() -> CheckResult:
        host = bare.split("/", 1)[0].split(":", 1)[0]
        if not dns_resolves(host):
            return CheckResult(status=BROKEN)      # domain is dead: verified
        return CheckResult(status=UNREACHABLE)     # resolves but no answer

    for attempt in range(2):
        try:
            resp = await client.get(f"https://{bare}", timeout=10)
            status = classify_code(resp.status_code)
            if status == BROKEN and 400 <= resp.status_code < 500 and _root_retry:
                root = root_of(target)
                if root:  # dead deep link - judge the site by its root
                    return await check_url(client, root, robots_cache,
                                           _root_retry=False)
            extra = _full_scan(resp) if status == WORKING else {}
            return CheckResult(status=status, http_code=resp.status_code,
                               **extra)
        except (ssl.SSLError, ssl.SSLCertVerificationError, httpx.ConnectError) as e:
            if "ssl" in str(e).lower() or "certificate" in str(e).lower():
                break  # cert problem: try plain http below
            if attempt == 1:
                return _dead_or_unreachable()
        except httpx.HTTPError:
            if attempt == 1:
                return _dead_or_unreachable()
        await asyncio.sleep(1.0)

    try:
        resp = await client.get(f"http://{bare}", timeout=10)
        status = classify_code(resp.status_code)
        if status == WORKING:
            extra = _full_scan(resp)
            return CheckResult(status=NO_SSL, http_code=resp.status_code,
                               **extra)
        if status == PROTECTED:
            return CheckResult(status=PROTECTED, http_code=resp.status_code)
        return CheckResult(status=BROKEN, http_code=resp.status_code)
    except httpx.HTTPError:
        return _dead_or_unreachable()


async def _check_all(urls: dict[str, str], concurrency: int,
                     progress=None, on_result=None) -> dict[str, CheckResult]:
    robots_cache: dict = {}
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, CheckResult] = {}
    done = 0

    async with httpx.AsyncClient(
        headers=BROWSER_HEADERS, follow_redirects=True, verify=True
    ) as client:
        async def one(biz_id: str, url: str) -> None:
            nonlocal done
            async with sem:
                try:
                    results[biz_id] = await check_url(client, url, robots_cache)
                except Exception:
                    results[biz_id] = CheckResult(status=BROKEN)
                done += 1
                if on_result:  # stream each finished check to the caller
                    on_result(biz_id, results[biz_id])
                if progress and done % 25 == 0:
                    progress(f"checked {done}/{len(urls)} sites")

        await asyncio.gather(*(one(b, u) for b, u in urls.items()))
    return results


def run_checks(urls: dict[str, str], concurrency: int = 12,
               progress=None, on_result=None) -> dict[str, CheckResult]:
    """Check {business_id: url} concurrently. Sync facade over asyncio.

    on_result(biz_id, CheckResult) fires as each site finishes (event-loop
    thread) - lets callers persist incrementally so watchers see a find
    appear live instead of all at once."""
    if not urls:
        return {}
    return asyncio.run(_check_all(urls, concurrency, progress, on_result))
