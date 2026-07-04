"""Shared config + Playwright helpers for the Modern Love archiver.

The NYT edge (DataDome + Cloudflare) rejects any client that doesn't look like a
real user: curl and Playwright's headless shell both get a 774-byte 403. What
gets through is a *headed* full-Chromium window that (a) warms up on the
homepage to collect clearance cookies and (b) navigates to each article with a
referer, exactly as a human clicking a link would. That recipe lives here so the
login and fetch scripts share one source of truth.
"""

from __future__ import annotations

import gzip
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".pw-browsers"))

DATA = ROOT / "data"
PROFILE = ROOT / ".pw-profile"          # persistent login lives here
HTML_DIR = DATA / "html"
MD_DIR = DATA / "markdown"
IMG_DIR = DATA / "images"
FONTS_DIR = DATA / "fonts"

# League Spartan (SIL OFL) — Standard Ebooks' titling face, used on the cover
# and for chapter titles. Fetched on demand so the repo stays code-only.
FONT_WEIGHTS = (400, 700, 900)
_FONT_URL = ("https://cdn.jsdelivr.net/npm/@fontsource/league-spartan/files/"
             "league-spartan-latin-{w}-normal.woff2")


def norm_url(url: str) -> str:
    """Canonical form of an article URL for dedupe across sources: https, a
    lowercased host, and the path only (no query, fragment, or trailing slash)."""
    p = urllib.parse.urlsplit(url.strip())
    return f"https://{p.netloc.lower()}{p.path.rstrip('/')}"


def fetch_url(url: str, timeout: int = 60) -> bytes:
    """GET a URL, transparently handling gzip (used for assets, not NYT)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def ensure_fonts() -> None:
    """Download the League Spartan weights into data/fonts if missing."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for w in FONT_WEIGHTS:
        dest = FONTS_DIR / f"league-spartan-{w}.woff2"
        if not dest.exists() or dest.stat().st_size < 2000:
            dest.write_bytes(fetch_url(_FONT_URL.format(w=w)))

HOME = "https://www.nytimes.com/"
# UA major version tracks the bundled Chromium (149.x) so it matches the engine.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# Injected before every page load to hide the most obvious automation tell.
_STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"


def make_context(pw, headless: bool = False):
    """Open the persistent, login-bearing browser context."""
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        user_agent=UA,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    ctx.add_init_script(_STEALTH)
    return ctx


def warmup(page) -> int:
    """Visit the homepage to collect DataDome/Cloudflare clearance cookies."""
    r = page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(2.5)
    return r.status if r else 0


def load_article(page, url: str, tries: int = 3):
    """Navigate to an article like a human (referer + retry). Returns the
    Response of the last attempt; caller inspects status and page.content()."""
    resp = None
    for attempt in range(tries):
        resp = page.goto(url, referer=HOME, wait_until="domcontentloaded", timeout=60_000)
        status = resp.status if resp else 0
        if status == 200:
            # Let the body/JSON settle without waiting for never-idle ad traffic.
            try:
                page.wait_for_selector("script#__preloadedData, article", timeout=8_000)
            except Exception:
                time.sleep(2)
            return resp
        # A 403 here is a soft challenge; pause and retry the same URL.
        time.sleep(4 + 3 * attempt)
    return resp
