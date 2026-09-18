"""
Timu Fetch — the fast, honest transport layer for Timu v2.
==========================================================

Three things live here:

1. ``AsyncHttpFetcher`` — an asyncio + HTTP/2 fetcher with per-host politeness,
   an on-disk SQLite cache with conditional requests (ETag / Last-Modified), and
   retry/backoff that honours ``Retry-After`` on 429 / 503. This is where the
   speed comes from: N sites and N pages per site go out concurrently instead of
   one-at-a-time, and an unchanged page costs a 304 instead of a full download.

2. ``BrowserFetcher`` — Playwright (Chromium) for pages whose content is built by
   JavaScript. It renders, optionally scrolls to trigger lazy loading, and —
   usefully — records the JSON/XHR endpoints the page itself calls, so Timu can
   tell you "this site has its own API, use that instead".

3. ``discover_urls`` — sitemap.xml (incl. the Sitemap: lines in robots.txt),
   RSS/Atom feeds, ``rel="next"`` pagination chains, and same-host links. Finding
   the site's own structured entry points is what actually unlocks large-scale
   extraction.

What is deliberately NOT here
-----------------------------
No fingerprint/stealth patching, no User-Agent spoofing, no CAPTCHA or
challenge solving, no proxy/IP rotation, no cookie or paywall circumvention.
Timu identifies itself as TimuBot on every request (browser included), obeys
robots.txt by default, backs off when a server says 429, and stops when a site
says no. A blocked site is a "use the API / ask for access" problem, not a
"hide harder" problem — ``discover_urls`` and ``BrowserFetcher.api_hits`` exist
precisely to give you the legitimate route.

Standalone smoke test:

    python timu_fetch.py https://reactome.org/ https://string-db.org/
"""

from __future__ import annotations

import asyncio
import gzip
import html as _html
import hashlib
import json
import re
import time
import urllib.parse as up
import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

TIMU_UA = "TimuBot/2.0 (+data-extraction agent; respects robots.txt; contact: site owner via 429/robots)"

try:                                                    # fast path
    import httpx
    HAVE_HTTPX = True
except Exception:                                       # pragma: no cover
    HAVE_HTTPX = False

try:
    from playwright.async_api import async_playwright    # noqa: F401
    HAVE_PLAYWRIGHT = True
except Exception:
    HAVE_PLAYWRIGHT = False


# ------------------------------------------------------------------ result ----

@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int | None = None
    ok: bool = False
    body: str = ""
    content_type: str = ""
    elapsed_ms: int = 0
    error: str = ""
    from_cache: bool = False
    renderer: str = "http"                 # http | browser | cache
    blocked_by_robots: bool = False
    api_hits: list[dict] = field(default_factory=list)
    attempts: int = 1

    @property
    def text_ratio(self) -> float:
        if not self.body:
            return 0.0
        txt = re.sub(r"<[^>]+>", " ", self.body)
        txt = re.sub(r"\s+", " ", txt).strip()
        return len(txt) / max(len(self.body), 1)


# ------------------------------------------------------------------- cache ----

class PageCache:
    """Conditional-GET cache with two interchangeable backends.

    SQLite when the stdlib module is importable (normal desktops), otherwise a
    plain gzip-file directory. Some hardened Windows builds block the `_sqlite3`
    DLL, so the file backend is not a toy fallback — it is the tested path here.
    """

    def __init__(self, path: str | Path = ".timu_cache", ttl_s: int = 3600):
        self.ttl_s = ttl_s
        self.backend = "sqlite"
        try:
            import sqlite3                                   # noqa: PLC0415
            self.path = str(path if str(path).endswith(".sqlite") else f"{path}.sqlite")
            self._db = sqlite3.connect(self.path, check_same_thread=False)
            self._db.execute("""CREATE TABLE IF NOT EXISTS pages(
                url TEXT PRIMARY KEY, status INT, etag TEXT, last_modified TEXT,
                content_type TEXT, body BLOB, fetched_at REAL)""")
            self._db.commit()
        except Exception:
            self.backend = "files"
            self.path = str(path).removesuffix(".sqlite")
            self._dir = Path(self.path)
            self._dir.mkdir(parents=True, exist_ok=True)
            self._db = None

    def _key(self, url: str) -> Path:
        return self._dir / (hashlib.sha1(url.encode()).hexdigest() + ".tz")

    def get(self, url: str) -> dict | None:
        if self.backend == "sqlite":
            row = self._db.execute(
                "SELECT status,etag,last_modified,content_type,body,fetched_at "
                "FROM pages WHERE url=?", (url,)).fetchone()
            if not row:
                return None
            status, etag, lm, ct, blob, ts = row
        else:
            p = self._key(url)
            if not p.exists():
                return None
            try:
                rec = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
            except Exception:
                return None
            status, etag, lm, ct, ts = (rec["status"], rec["etag"], rec["last_modified"],
                                        rec["content_type"], rec["fetched_at"])
            return {"status": status, "etag": etag, "last_modified": lm, "content_type": ct,
                    "body": rec["body"], "fetched_at": ts,
                    "fresh": (time.time() - ts) < self.ttl_s}
        try:
            text = gzip.decompress(blob).decode("utf-8", "replace")
        except Exception:
            text = (blob or b"").decode("utf-8", "replace")
        return {"status": status, "etag": etag, "last_modified": lm, "content_type": ct,
                "body": text, "fetched_at": ts, "fresh": (time.time() - ts) < self.ttl_s}

    def put(self, url: str, status: int, headers: dict, body: str, content_type: str):
        etag, lm = headers.get("etag"), headers.get("last-modified")
        if self.backend == "sqlite":
            self._db.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?)",
                             (url, status, etag, lm, content_type,
                              gzip.compress(body.encode("utf-8", "replace")), time.time()))
            self._db.commit()
        else:
            rec = {"url": url, "status": status, "etag": etag, "last_modified": lm,
                   "content_type": content_type, "body": body, "fetched_at": time.time()}
            self._key(url).write_bytes(gzip.compress(
                json.dumps(rec, ensure_ascii=False).encode("utf-8")))

    def touch(self, url: str):
        if self.backend == "sqlite":
            self._db.execute("UPDATE pages SET fetched_at=? WHERE url=?", (time.time(), url))
            self._db.commit()
        else:
            rec = self.get(url)
            if rec:
                self.put(url, rec["status"],
                         {"etag": rec["etag"], "last-modified": rec["last_modified"]},
                         rec["body"], rec["content_type"])

    def stats(self) -> dict:
        if self.backend == "sqlite":
            n, b = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(body)),0) FROM pages").fetchone()
        else:
            files = list(self._dir.glob("*.tz"))
            n, b = len(files), sum(f.stat().st_size for f in files)
        return {"pages": n, "compressed_bytes": b, "path": self.path, "backend": self.backend}

    def clear(self):
        if self.backend == "sqlite":
            self._db.execute("DELETE FROM pages")
            self._db.commit()
        else:
            for f in self._dir.glob("*.tz"):
                f.unlink(missing_ok=True)


# ------------------------------------------------------------- http fetcher ----

@dataclass
class FetchConfig:
    timeout: float = 20.0
    total_concurrency: int = 16
    per_host_concurrency: int = 2
    per_host_delay: float = 0.5
    retries: int = 2
    max_bytes: int = 5_000_000
    respect_robots: bool = True
    user_agent: str = TIMU_UA
    http2: bool = True
    use_cache: bool = True
    cache_ttl_s: int = 3600
    cache_path: str = ".timu_cache.sqlite"
    verify_ssl: bool = True
    max_retry_after: float = 20.0          # never sleep longer than this on 429


class AsyncHttpFetcher:
    """Concurrent, cache-aware, robots-aware HTTP fetcher."""

    def __init__(self, cfg: FetchConfig | None = None):
        if not HAVE_HTTPX:
            raise RuntimeError("httpx not installed — pip install httpx h2")
        self.cfg = cfg or FetchConfig()
        self.cache = PageCache(self.cfg.cache_path, self.cfg.cache_ttl_s) if self.cfg.use_cache else None
        self._client: Any = None
        self._sem = asyncio.Semaphore(self.cfg.total_concurrency)
        self._host_sem: dict[str, asyncio.Semaphore] = {}
        self._host_last: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.notes: list[str] = []

    async def __aenter__(self):
        limits = httpx.Limits(max_connections=self.cfg.total_concurrency,
                              max_keepalive_connections=self.cfg.total_concurrency)
        self._client = httpx.AsyncClient(
            http2=self.cfg.http2, follow_redirects=True, timeout=self.cfg.timeout,
            limits=limits, verify=self.cfg.verify_ssl,
            headers={"User-Agent": self.cfg.user_agent,
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                               "application/json;q=0.9,*/*;q=0.8",
                     "Accept-Language": "en,hi;q=0.8",
                     "Accept-Encoding": "gzip, deflate, br"})
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    # -- politeness --------------------------------------------------------
    def _hsem(self, host: str) -> asyncio.Semaphore:
        if host not in self._host_sem:
            self._host_sem[host] = asyncio.Semaphore(self.cfg.per_host_concurrency)
        return self._host_sem[host]

    async def _pace(self, host: str):
        last = self._host_last.get(host)
        if last is not None:
            wait = self.cfg.per_host_delay - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._host_last[host] = time.monotonic()

    # -- robots ------------------------------------------------------------
    async def robots(self, url: str) -> robotparser.RobotFileParser | None:
        origin = up.urlsplit(url)._replace(path="", query="", fragment="").geturl()
        if origin in self._robots:
            return self._robots[origin]
        rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        try:
            r = await self._client.get(up.urljoin(origin, "/robots.txt"),
                                       timeout=min(8.0, self.cfg.timeout))
            if r.status_code < 400 and r.text.strip():
                rp.parse(r.text.splitlines())                      # type: ignore[union-attr]
                rp._timu_raw = r.text                              # type: ignore[attr-defined]
            else:
                rp = None
        except Exception:
            rp = None
        self._robots[origin] = rp
        return rp

    async def allowed(self, url: str) -> bool:
        if not self.cfg.respect_robots:
            return True
        rp = await self.robots(url)
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.cfg.user_agent, url)
        except Exception:
            return True

    async def crawl_delay(self, url: str) -> float | None:
        rp = await self.robots(url)
        if rp is None:
            return None
        try:
            d = rp.crawl_delay(self.cfg.user_agent)
            return float(d) if d else None
        except Exception:
            return None

    # -- get ---------------------------------------------------------------
    async def get(self, url: str) -> FetchResult:
        res = FetchResult(url=url)
        if not url.startswith(("http://", "https://")):
            res.error = "not an http(s) url"
            return res
        if not await self.allowed(url):
            res.error = "disallowed by robots.txt"
            res.blocked_by_robots = True
            return res

        host = up.urlsplit(url).netloc
        cd = await self.crawl_delay(url)
        cached = self.cache.get(url) if self.cache else None
        if cached and cached["fresh"]:
            res.status, res.body, res.ok = cached["status"], cached["body"], True
            res.content_type, res.final_url = cached["content_type"], url
            res.from_cache, res.renderer = True, "cache"
            return res

        headers = {}
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]

        t0 = time.monotonic()
        async with self._sem, self._hsem(host):
            for attempt in range(1, self.cfg.retries + 2):
                res.attempts = attempt
                if cd:
                    await asyncio.sleep(min(cd, 5.0))
                await self._pace(host)
                try:
                    r = await self._client.get(url, headers=headers)
                    res.status, res.final_url = r.status_code, str(r.url)
                    res.content_type = (r.headers.get("content-type") or "").split(";")[0].strip()

                    if r.status_code == 304 and cached:
                        res.body, res.ok, res.from_cache = cached["body"], True, True
                        res.renderer = "cache"
                        if self.cache:
                            self.cache.touch(url)
                        break
                    if r.status_code in (429, 503) and attempt <= self.cfg.retries:
                        ra = r.headers.get("retry-after")
                        try:
                            delay = min(float(ra), self.cfg.max_retry_after) if ra else 2.0 * attempt
                        except ValueError:
                            delay = 2.0 * attempt
                        self.notes.append(f"{host}: {r.status_code}, backing off {delay:g}s "
                                          f"(server asked)")
                        await asyncio.sleep(delay)
                        continue
                    body = r.text
                    if len(body) > self.cfg.max_bytes:
                        body = body[: self.cfg.max_bytes]
                    res.body, res.ok = body, r.status_code < 400 and bool(body)
                    if not res.ok:
                        res.error = f"HTTP {r.status_code}"
                    elif self.cache:
                        self.cache.put(url, r.status_code, dict(r.headers), body, res.content_type)
                    break
                except Exception as e:
                    kind = e.__class__.__name__
                    msg = str(e)
                    if "403" in msg and "CONNECT" in msg:
                        res.error = ("blocked by network policy (sandbox allowlist) — "
                                     "run Timu locally or allow this domain")
                        break
                    res.error = f"{kind}: {msg[:140]}"
                    if attempt <= self.cfg.retries:
                        await asyncio.sleep(0.6 * attempt * attempt)
                        continue
        res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return res

    async def get_many(self, urls: Sequence[str]) -> list[FetchResult]:
        return list(await asyncio.gather(*(self.get(u) for u in urls)))

    async def get_json(self, url: str) -> Any:
        r = await self.get(url)
        if not r.ok:
            return None
        try:
            return json.loads(r.body)
        except Exception:
            return None


# --------------------------------------------------------- browser fetcher ----

JS_SHELL_MARKERS = ("__NEXT_DATA__", "window.__NUXT__", "ng-app", "data-reactroot",
                    "__remixContext", "window.__INITIAL_STATE__", "id=\"root\"",
                    "id=\"app\"", "enable javascript", "requires javascript")


def looks_js_rendered(res: FetchResult) -> tuple[bool, str]:
    """Heuristic: did the HTTP response leave the real content to the browser?"""
    if not res.ok or not res.body:
        return False, ""
    low = res.body.lower()
    txt_len = len(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", res.body)).strip())
    if txt_len < 900 and any(m.lower() in low for m in JS_SHELL_MARKERS):
        return True, f"thin html ({txt_len} chars of text) + SPA marker"
    if res.text_ratio < 0.045 and txt_len < 2500:
        return True, f"text/html ratio {res.text_ratio:.3f}"
    if "<noscript" in low and txt_len < 1200:
        return True, "noscript fallback only"
    return False, ""


class BrowserFetcher:
    """Playwright Chromium renderer. Identifies itself; no stealth patching."""

    def __init__(self, cfg: FetchConfig | None = None, *, headless: bool = True,
                 wait_until: str = "domcontentloaded", settle_ms: int = 1200,
                 scroll: int = 3, capture_api: bool = True, block_media: bool = True):
        self.cfg = cfg or FetchConfig()
        self.headless, self.wait_until = headless, wait_until
        self.settle_ms, self.scroll = settle_ms, scroll
        self.capture_api, self.block_media = capture_api, block_media
        self._pw = self._browser = self._ctx = None
        self.available = HAVE_PLAYWRIGHT

    async def __aenter__(self):
        if not HAVE_PLAYWRIGHT:
            raise RuntimeError("playwright not installed — pip install playwright && "
                               "python -m playwright install chromium")
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        base_ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "HeadlessChrome/120.0 Safari/537.36")
        self._ctx = await self._browser.new_context(
            user_agent=f"{base_ua} {TIMU_UA}",       # append, never disguise
            viewport={"width": 1440, "height": 900},
            java_script_enabled=True)
        if self.block_media:                          # speed: skip images/fonts/video
            async def _route(route):
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()
            await self._ctx.route("**/*", _route)
        return self

    async def __aexit__(self, *exc):
        for obj, meth in ((self._ctx, "close"), (self._browser, "close"), (self._pw, "stop")):
            try:
                if obj:
                    await getattr(obj, meth)()
            except Exception:
                pass

    async def get(self, url: str, *, wait_for: str | None = None) -> FetchResult:
        res = FetchResult(url=url, renderer="browser")
        t0 = time.monotonic()
        page = await self._ctx.new_page()                  # type: ignore[union-attr]
        hits: list[dict] = []

        if self.capture_api:
            async def on_resp(r):
                try:
                    ct = (r.headers.get("content-type") or "").lower()
                    if "json" in ct and r.request.resource_type in ("xhr", "fetch"):
                        hits.append({"url": r.url, "status": r.status,
                                     "method": r.request.method, "content_type": ct})
                except Exception:
                    pass
            page.on("response", on_resp)

        try:
            r = await page.goto(url, wait_until=self.wait_until,
                                timeout=self.cfg.timeout * 1000)
            res.status = r.status if r else None
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=8000)
                except Exception:
                    pass
            for _ in range(max(0, self.scroll)):
                await page.mouse.wheel(0, 2400)
                await page.wait_for_timeout(350)
            await page.wait_for_timeout(self.settle_ms)
            res.body = await page.content()
            res.final_url = page.url
            res.content_type = "text/html"
            res.ok = bool(res.body) and (res.status or 200) < 400
            if not res.ok:
                res.error = f"HTTP {res.status}"
        except Exception as e:
            res.error = f"{e.__class__.__name__}: {str(e)[:160]}"
        finally:
            seen, uniq = set(), []
            for h in hits:
                key = h["url"].split("?")[0]
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(h)
            res.api_hits = uniq[:40]
            await page.close()
        res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return res


def chromium_available() -> tuple[bool, str]:
    """Is a Chromium build on disk? Filesystem check only — never launches a process,
    so it is safe on hosts that block subprocess creation."""
    if not HAVE_PLAYWRIGHT:
        return False, "playwright package not installed"
    import os
    roots = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env not in ("0",):
        roots.append(Path(env))
    home = Path.home()
    roots += [home / "AppData" / "Local" / "ms-playwright",
              home / ".cache" / "ms-playwright",
              home / "Library" / "Caches" / "ms-playwright"]
    try:
        import playwright
        roots.append(Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers")
    except Exception:
        pass
    for r in roots:
        try:
            if r.exists() and any(c.name.startswith("chromium") for c in r.iterdir()):
                return True, str(r)
        except Exception:
            continue
    return False, "no chromium build found — run: python -m playwright install chromium"


# ---------------------------------------------------------------- discovery ----

SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap.xml.gz")
FEED_RE = re.compile(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', re.I)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
NEXT_RE = re.compile(r'<link[^>]+rel=["\']next["\'][^>]*>', re.I)
A_NEXT_RE = re.compile(r'<a[^>]+rel=["\']next["\'][^>]*href=["\']([^"\']+)["\']', re.I)


_MISSING_LIB_RE = re.compile(r"error while loading shared libraries:\s*([^:]+):")
_BROWSER_PROBE: tuple[bool, str] | None = None


def browser_hint(error_text: str) -> str:
    """Turn a Playwright launch failure into the one line that fixes it."""
    t = error_text or ""
    m = _MISSING_LIB_RE.search(t)
    if m:
        lib = m.group(1).strip()
        return (f"Chromium binary hai par OS library `{lib}` missing hai. Streamlit Cloud / "
                f"Docker pe `packages.txt` (ya apt-get) se system deps chahiye — repo ke "
                f"packages.txt me list hai; locally: `python -m playwright install-deps`")
    if "Executable doesn't exist" in t or "no chromium build" in t.lower():
        return "Chromium install nahi hai — `python -m playwright install chromium` chalao"
    if "Timeout" in t or "timeout" in t:
        return "browser launch timeout ho gaya (host pe memory/CPU kam ho sakta hai)"
    if "Permission" in t or "EACCES" in t:
        return "browser binary chal nahi paya (permission denied)"
    return t.strip().splitlines()[0][:160] if t.strip() else "unknown browser launch error"


def browser_probe(force: bool = False) -> tuple[bool, str]:
    """Actually try to start Chromium once and cache the verdict.

    `chromium_available()` only checks that the binary is on disk; a hosted
    environment can have the binary and still fail to launch it for want of
    system libraries. This answers the question that matters.
    """
    global _BROWSER_PROBE
    if _BROWSER_PROBE is not None and not force:
        return _BROWSER_PROBE
    ok, why = chromium_available()
    if not ok:
        _BROWSER_PROBE = (False, browser_hint(why))
        return _BROWSER_PROBE

    def _try() -> tuple[bool, str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch(args=["--no-sandbox"])
                v = b.version
                b.close()
            return True, f"chromium {v} launches fine"
        except Exception as e:                                       # noqa: BLE001
            return False, browser_hint(f"{e.__class__.__name__}: {e}")

    import concurrent.futures as _cf                                 # noqa: PLC0415
    with _cf.ThreadPoolExecutor(max_workers=1) as ex:                # never inside a loop
        try:
            _BROWSER_PROBE = ex.submit(_try).result(timeout=90)
        except Exception as e:                                       # noqa: BLE001
            _BROWSER_PROBE = (False, browser_hint(f"{e.__class__.__name__}: {e}"))
    return _BROWSER_PROBE


def _xml_locs(text: str) -> tuple[list[str], list[str]]:
    """Return (page urls, nested sitemap urls) from a sitemap document."""
    pages, maps = [], []
    try:
        root = ET.fromstring(text.strip())
    except Exception:
        return pages, maps
    tag = root.tag.lower()
    for el in root.iter():
        name = el.tag.split("}")[-1].lower()
        if name == "loc" and el.text:
            (maps if "sitemapindex" in tag else pages).append(el.text.strip())
    return pages, maps


_NON_PAGE_RE = re.compile(
    r"\.(?:xml|xml\.gz|rss|atom|json|jsonld|csv|tsv|txt|pdf|zip|gz|tar|"
    r"ico|png|jpe?g|gif|webp|avif|bmp|svg|css|js|mjs|map|"
    r"woff2?|ttf|otf|eot|mp[34]|m4[av]|wav|avi|mov|webm|"
    r"docx?|xlsx?|pptx?|rtf|epub)$", re.I)
_FEED_PATH_RE = re.compile(r"(?:^|/)(?:feed|feeds|rss|atom)/?$", re.I)
# infrastructure paths that never hold content
_JUNK_PATH_RE = re.compile(r"/cdn-cgi/|/wp-json/|/xmlrpc\.php|/__|/cgi-bin/", re.I)


def is_page_like(url: str) -> bool:
    """Is this URL an HTML page (worth running the extractors on)?

    Sitemaps, feeds and data files are found *by* discovery and are useful as
    leads, but feeding them to an HTML extractor produces noise — a feed is XML,
    not a page.
    """
    clean = url.split("#")[0]
    path = up.urlsplit(clean).path
    if _NON_PAGE_RE.search(path) or _FEED_PATH_RE.search(path) or _JUNK_PATH_RE.search(path):
        return False
    if len(up.urlsplit(clean).query) > 220:            # tracking/session junk, not a page
        return False
    q = up.urlsplit(clean).query.lower()
    return not any(t in q for t in ("format=feed", "format=rss", "format=atom", "output=rss"))


async def discover_urls(fetcher: AsyncHttpFetcher, start_url: str, *,
                        want: int = 25, use_sitemap: bool = True,
                        use_feeds: bool = True, follow_next: int = 5,
                        same_host_links: bool = True,
                        first: FetchResult | None = None) -> dict:
    """Find the site's own structured entry points. Returns a dict report."""
    origin = up.urlsplit(start_url)._replace(path="", query="", fragment="").geturl()
    host = up.urlsplit(start_url).netloc
    out: dict[str, Any] = {"sitemaps": [], "feeds": [], "pagination": [], "urls": [],
                           "source": {}}
    first = first or await fetcher.get(start_url)

    # 1. sitemaps — from robots.txt, then well-known paths
    if use_sitemap:
        cand = []
        rp = await fetcher.robots(start_url)
        raw = getattr(rp, "_timu_raw", "") if rp else ""
        cand += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", raw or "")
        cand += [up.urljoin(origin, p) for p in SITEMAP_PATHS]
        seen_map = set()
        t_start = time.monotonic()
        budget = getattr(fetcher.cfg, "discovery_budget_s", 8.0)
        cap = getattr(fetcher.cfg, "max_sitemap_bytes", 2_000_000)
        for sm in cand[:6]:
            if sm in seen_map or (time.monotonic() - t_start) > budget:
                continue
            seen_map.add(sm)
            r = await fetcher.get(sm)
            if not r.ok or "<" not in r.body[:400] or len(r.body) > cap:
                continue
            pages, nested = _xml_locs(r.body)
            for n in nested[:2]:
                if (time.monotonic() - t_start) > budget:
                    break
                rn = await fetcher.get(n)
                if rn.ok and len(rn.body) <= cap:
                    p2, _ = _xml_locs(rn.body)
                    pages += p2
            if pages:
                out["sitemaps"].append({"url": sm, "urls_found": len(pages)})
                for u in pages:
                    if u not in out["urls"]:
                        out["urls"].append(u)
                        out["source"][u] = "sitemap"
                if len(out["urls"]) >= want * 3:
                    break

    # 2. feeds
    if use_feeds and first.ok:
        for tagtxt in FEED_RE.findall(first.body)[:5]:
            m = HREF_RE.search(tagtxt)
            if m:
                out["feeds"].append(up.urljoin(first.final_url or start_url,
                                               _html.unescape(m.group(1))))

    # 3. rel=next pagination chain
    if follow_next and first.ok:
        cur, body = first.final_url or start_url, first.body
        for _ in range(follow_next):
            nxt = None
            m = NEXT_RE.search(body)
            if m:
                h = HREF_RE.search(m.group(0))
                if h:
                    nxt = up.urljoin(cur, _html.unescape(h.group(1)))
            if not nxt:
                m2 = A_NEXT_RE.search(body)
                if m2:
                    nxt = up.urljoin(cur, _html.unescape(m2.group(1)))
            if not nxt or nxt == cur:
                break
            out["pagination"].append(nxt)
            if nxt not in out["urls"]:
                out["urls"].append(nxt)
                out["source"][nxt] = "pagination"
            r = await fetcher.get(nxt)
            if not r.ok:
                break
            cur, body = nxt, r.body

    # 4. same-host links as a fallback / top-up
    if same_host_links and first.ok and len(out["urls"]) < want:
        base = first.final_url or start_url
        for href in HREF_RE.findall(first.body):
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            u = up.urljoin(base, _html.unescape(href)).split("#")[0].rstrip("/")
            if up.urlsplit(u).netloc != host:
                continue
            if re.search(r"\.(?:pdf|zip|png|jpe?g|gif|svg|mp4|mp3|docx?|xlsx?|css|js)$", u, re.I):
                continue
            if u in out["urls"] or u.rstrip("/") == base.rstrip("/"):
                continue
            out["urls"].append(u)
            out["source"][u] = "link"
            if len(out["urls"]) >= want:
                break

    out["urls"] = out["urls"][: want * 3]
    out["counts"] = {"sitemap": sum(1 for v in out["source"].values() if v == "sitemap"),
                     "pagination": sum(1 for v in out["source"].values() if v == "pagination"),
                     "link": sum(1 for v in out["source"].values() if v == "link"),
                     "feeds": len(out["feeds"])}
    return out


BLOCK_STATUSES = (401, 403, 405, 406, 429, 451)


def parse_robots_groups(raw: str) -> tuple[dict[str, dict], list[str]]:
    """Group robots.txt rules per user-agent and collect its Sitemap: lines.

    stdlib's RobotFileParser answers "may I fetch this URL" but will not tell you
    *what a site does permit* — which is exactly what you need when a fetch was
    refused. Hence this small parser.
    """
    groups: dict[str, dict] = {}
    current: list[str] = []
    sitemaps: list[str] = []
    expecting_agents = False
    for line in (raw or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "sitemap":
            if value:
                sitemaps.append(value)
            continue
        if field == "user-agent":
            if not expecting_agents:
                current = []
                expecting_agents = True
            agent = value.lower() or "*"
            current.append(agent)
            groups.setdefault(agent, {"disallow": [], "allow": [], "crawl_delay": None})
            continue
        expecting_agents = False
        for agent in current or ["*"]:
            g = groups.setdefault(agent, {"disallow": [], "allow": [], "crawl_delay": None})
            if field == "disallow":
                g["disallow"].append(value)
            elif field == "allow":
                g["allow"].append(value)
            elif field in ("crawl-delay", "crawl_delay"):
                try:
                    g["crawl_delay"] = float(value)
                except ValueError:
                    pass
    return groups, sitemaps


async def permitted_routes(f: "AsyncHttpFetcher", url: str, *, want: int = 8,
                           check_sitemaps: bool = True) -> dict:
    """A site refused the fetch — report what it *does* permit.

    Reads robots.txt (which usually serves even when pages 403), works out which
    user-agent group applies to us, and lists the sitemaps the site advertises
    with a few sample URLs. No probing of undeclared paths, no retrying the
    refused URL with a different identity: this only reads what the site
    publishes about itself.
    """
    origin = up.urlsplit(url)._replace(path="", query="", fragment="").geturl()
    out: dict[str, Any] = {"robots_url": up.urljoin(origin, "/robots.txt"),
                           "robots_available": False, "applies_to": None,
                           "disallow": [], "allow": [], "crawl_delay": None,
                           "sitemaps": [], "sample_urls": [], "verdict": "", "notes": []}
    rp = await f.robots(url)
    raw = getattr(rp, "_timu_raw", "") if rp else ""
    ua = (f.cfg.user_agent or "timubot").lower()

    if not raw.strip():
        out["verdict"] = ("robots.txt nahi mila / khaali hai — refusal server ya CDN side se "
                          "hai (user-agent ya datacenter IP filter), robots rules ki wajah se "
                          "nahi. Site ka official API / data feed maango, ya apne network se "
                          "chalao.")
        out["notes"].append(out["verdict"])
        return out

    out["robots_available"] = True
    groups, sitemaps = parse_robots_groups(raw)
    picked = next((a for a in groups if a != "*" and a and a in ua), None) or \
        ("*" if "*" in groups else next(iter(groups), None))
    g = groups.get(picked or "*", {"disallow": [], "allow": [], "crawl_delay": None})
    out["applies_to"] = picked
    out["disallow"] = [d for d in g["disallow"] if d][:40]
    out["allow"] = [a for a in g["allow"] if a][:40]
    out["crawl_delay"] = g.get("crawl_delay")

    blanket = any(d.strip() == "/" for d in g["disallow"])
    if blanket and not g["allow"]:
        out["verdict"] = (f"robots.txt (group '{picked}') poori site pe automated access mana "
                          f"karta hai. Yahan Timu ruk jata hai — official API ya written "
                          f"permission hi aage ka raasta hai.")
        out["notes"].append(out["verdict"])
        return out

    if check_sitemaps:
        cand = sitemaps[:4] or [up.urljoin(origin, p) for p in SITEMAP_PATHS[:2]]
        for sm in cand:
            r = await f.get(sm)
            entry = {"url": sm, "status": r.status if r.ok else (r.status or r.error),
                     "urls_found": 0, "sample": []}
            if r.ok and "<" in r.body[:400]:
                pages, nested = _xml_locs(r.body)
                if not pages and nested:
                    entry["nested_sitemaps"] = len(nested)
                    entry["sample"] = nested[:want]
                else:
                    entry["urls_found"] = len(pages)
                    entry["sample"] = pages[:want]
                for u in entry["sample"]:
                    if u not in out["sample_urls"]:
                        out["sample_urls"].append(u)
            out["sitemaps"].append(entry)

    allowed_txt = (", ".join(out["allow"][:6]) if out["allow"]
                   else "robots.txt me koi explicit Allow nahi, par poori site par blanket "
                        "Disallow bhi nahi hai")
    out["verdict"] = (f"robots.txt allow karta hai ({allowed_txt}); page fetch phir bhi "
                      f"refuse hua, to block user-agent/IP level pe hai. "
                      + (f"Site khud {len(out['sample_urls'])} URL sitemap me publish karti hai "
                         f"— wahi structured raasta hai."
                         if out["sample_urls"] else
                         "Sitemap se bhi kuch nahi mila — official API/feed maango."))
    out["notes"].append(out["verdict"])
    if out["crawl_delay"]:
        out["notes"].append(f"robots.txt Crawl-delay {out['crawl_delay']}s maangta hai — "
                            f"Timu use follow karta hai.")
    return out


# ------------------------------------------------------------- orchestration ----

async def resolve_first_ok(f: AsyncHttpFetcher, candidates: Sequence[str]) -> FetchResult:
    """Try candidate URLs in order (bare-name targets expand to several TLDs)."""
    last: FetchResult | None = None
    for c in candidates:
        r = await f.get(c)
        if r.ok:
            return r
        last = r
        if r.blocked_by_robots or (r.status and r.status < 500):
            if len(candidates) == 1:
                return r
    return last or FetchResult(url=candidates[0] if candidates else "", error="no candidates")


async def smart_fetch_site(url: str, *, cfg: FetchConfig | None = None,
                           pages: int = 1, render: str = "auto",
                           discover: bool = True, wait_for: str | None = None,
                           browser: BrowserFetcher | None = None,
                           fetcher: AsyncHttpFetcher | None = None,
                           candidates: Sequence[str] | None = None) -> dict:
    """Fetch one site: HTTP first, escalate to the browser only if needed."""
    own_fetcher = fetcher is None
    cfg = cfg or FetchConfig()
    f = fetcher or AsyncHttpFetcher(cfg)
    if own_fetcher:
        await f.__aenter__()
    notes: list[str] = []
    try:
        first = await (resolve_first_ok(f, candidates) if candidates else f.get(url))
        url = first.url or url
        use_browser = render == "browser"
        if render == "auto" and first.ok:
            js, why = looks_js_rendered(first)
            if js:
                use_browser = True
                notes.append(f"auto-escalated to browser render: {why}")
        advice: dict = {}
        if not first.ok and (first.blocked_by_robots or first.status in BLOCK_STATUSES):
            if first.blocked_by_robots:
                notes.append("robots.txt ne is URL ko disallow kiya hai — Timu fetch nahi karega")
            else:
                notes.append(f"HTTP {first.status} — server refused TimuBot; "
                             f"checking what this site does permit")
            advice = await permitted_routes(f, url)
            notes.extend(advice.get("notes") or [])

        results: list[FetchResult] = []
        disc: dict = {}
        if use_browser:
            try:
                if browser is not None:
                    r = await browser.get(url, wait_for=wait_for)
                elif HAVE_PLAYWRIGHT:
                    async with BrowserFetcher(cfg) as b:
                        r = await b.get(url, wait_for=wait_for)
                else:
                    r = first
                    notes.append("browser render requested but Playwright is not installed "
                                 "(pip install playwright && "
                                 "python -m playwright install chromium)")
            except Exception as e:                                   # noqa: BLE001
                r = first
                notes.append(f"browser render unavailable — "
                             f"{browser_hint(f'{e.__class__.__name__}: {e}')}; "
                             f"HTTP result use kiya")
            if r.ok:
                if r.api_hits:
                    notes.append(f"page calls {len(r.api_hits)} JSON endpoint(s) of its own — "
                                 f"see api_endpoints")
                results.append(r)
            else:
                notes.append(f"browser render failed ({r.error}); keeping HTTP result")
                results.append(first)
        else:
            results.append(first)

        if pages > 1 and first.ok:
            disc = await discover_urls(f, url, want=max(pages * 2, 12), first=first,
                                       use_sitemap=discover, use_feeds=discover)
            rank = {"sitemap": 0, "pagination": 1, "link": 2}
            cands_extra = [u for u in disc["urls"]
                           if u.rstrip("/") != (first.final_url or url).rstrip("/")
                           and is_page_like(u)]
            extra = sorted(cands_extra,
                           key=lambda u: rank.get((disc.get("source") or {}).get(u), 3)
                           )[: pages - 1]
            if extra:
                if use_browser and browser is not None:
                    for u in extra:
                        results.append(await browser.get(u, wait_for=wait_for))
                else:
                    results.extend(await f.get_many(extra))
        return {"url": url, "results": [r for r in results if r.ok] or results[:1],
                "all_results": results, "discovery": disc, "notes": notes,
                "advice": advice,
                "api_endpoints": results[0].api_hits if results else []}
    finally:
        if own_fetcher:
            await f.__aexit__(None, None, None)


async def fetch_sites(urls: Sequence[str], *, cfg: FetchConfig | None = None,
                      pages: int = 1, render: str = "auto", discover: bool = True,
                      wait_for: str | None = None, candidates_map: dict | None = None,
                      on_event=None) -> list[dict]:
    """Fetch many sites concurrently, sharing one HTTP client (and one browser)."""
    cfg = cfg or FetchConfig()
    say = on_event or (lambda e: None)
    need_browser = render == "browser" and HAVE_PLAYWRIGHT
    async with AsyncHttpFetcher(cfg) as f:
        browser = None
        try:
            if need_browser:
                try:
                    browser = await BrowserFetcher(cfg).__aenter__()
                except Exception as e:                               # noqa: BLE001
                    browser = None
                    render = "http"                                  # degrade, do not abort
                    say({"event": "warn",
                         "message": f"browser render unavailable — "
                                    f"{browser_hint(f'{e.__class__.__name__}: {e}')}; "
                                    f"HTTP render pe continue kar raha hoon"})

            async def one(u: str):
                say({"event": "site_start", "target": u})
                out = await smart_fetch_site(u, cfg=cfg, pages=pages, render=render,
                                             discover=discover, wait_for=wait_for,
                                             browser=browser, fetcher=f,
                                             candidates=(candidates_map or {}).get(u))
                out["target"] = u
                good = [r for r in out["all_results"] if r.ok]
                say({"event": "fetch_done", "target": u, "pages": len(good),
                     "renderer": (good[0].renderer if good else "none"),
                     "cached": sum(1 for r in good if r.from_cache),
                     "notes": out["notes"]})
                return out

            return list(await asyncio.gather(*(one(u) for u in urls)))
        finally:
            if browser:
                await browser.__aexit__(None, None, None)


def run_sync(coro):
    """Run an async Timu coroutine from sync code (engine, Flask, notebooks)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import threading
    box: dict = {}

    def runner():
        try:
            box["v"] = asyncio.run(coro)
        except Exception as e:                                       # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box.get("v")


# --------------------------------------------------------------------- main ----

if __name__ == "__main__":
    import sys
    targets = sys.argv[1:] or ["https://reactome.org/"]
    t0 = time.time()
    out = run_sync(fetch_sites(targets, pages=3, render="auto",
                               on_event=lambda e: print("[timu-fetch]", e)))
    for o in out:
        ok = [r for r in o["all_results"] if r.ok]
        print(f"\n{o['url']}  pages_ok={len(ok)}  "
              f"renderer={ok[0].renderer if ok else 'none'}  "
              f"discovery={o['discovery'].get('counts')}")
        for n in o["notes"]:
            print("   note:", n)
        for r in ok:
            print(f"   {r.status} {len(r.body):>8}B {r.elapsed_ms:>5}ms "
                  f"{'CACHE' if r.from_cache else '     '} {r.final_url[:90]}")
    print(f"\ntotal {time.time()-t0:.2f}s  httpx={HAVE_HTTPX} playwright={HAVE_PLAYWRIGHT}")
