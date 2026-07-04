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
import re
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


# The Modern Love Podcast shares the column's "Modern Love" kicker but is not the
# written essay. These host/producer bylines never appear on the column itself.
PODCAST_BYLINES = {"Anna Martin"}

# Curated non-essays that carry the column's kicker but aren't the written essay
# and evade the podcast rule: reader-story roundups, contest announcements and
# calls for submissions, and interactive companions. Keyed by canonical URL.
EXCLUDE_URLS = {
    norm_url(u) for u in (
        # Not the weekly essay: reader-story roundups, contest notices, calls
        # for submissions, interactive companions, editorial/anniversary
        # features, and the 20th-anniversary "classic" reprints (dupes of the
        # originals, which are kept under their original dates).
        "https://www.nytimes.com/2014/12/21/style/the-10-best-modern-love-columns-ever.html",
        "https://www.nytimes.com/2015/01/09/style/no-37-big-wedding-or-small.html",
        "https://www.nytimes.com/2015/02/13/style/the-36-questions-on-the-way-to-love.html",
        "https://www.nytimes.com/2017/11/10/style/modern-love-13-word-stories.html",
        "https://www.nytimes.com/2018/06/01/style/modern-love-13-word-stories.html",
        "https://www.nytimes.com/2019/02/15/style/modern-love-college-essay-contest.html",
        "https://www.nytimes.com/2020/06/12/style/modern-love-coronavirus-living-together.html",
        "https://www.nytimes.com/2022/02/11/style/what-is-black-love-today.html",
        "https://www.nytimes.com/2022/11/10/style/modern-love-tell-us-about-a-moment-of-regrettable-rage.html",
        "https://www.nytimes.com/2022/12/17/style/rage-regret-relationships.html",
        "https://www.nytimes.com/2023/12/11/style/modern-love-money-questions-partners.html",
        "https://www.nytimes.com/2024/02/21/style/modern-love-messages-screenshots.html",
        "https://www.nytimes.com/2024/10/11/style/modern-love-7-lessons.html",
        "https://www.nytimes.com/2024/10/11/style/modern-love-classic-my-body-doesnt-belong-to-you.html",
        "https://www.nytimes.com/2024/10/11/style/modern-love-essays-readers-stories.html",
        "https://www.nytimes.com/2024/10/11/style/modern-love-letters-younger-self.html",
        "https://www.nytimes.com/2024/10/11/style/modern-love-origin.html",
        "https://www.nytimes.com/2024/10/18/style/modern-love-classic-learning-to-measure-time-in-love-and-loss.html",
        "https://www.nytimes.com/2024/10/25/style/modern-love-classic-sometimes-its-not-you-or-the-math.html",
        "https://www.nytimes.com/2024/11/01/style/modern-love-classic-when-eve-and-eve-bit-the-apple.html",
        "https://www.nytimes.com/2025/06/26/style/same-sex-marriage-supreme-court.html",
        "https://www.nytimes.com/2025/09/18/style/modern-love-we-want-your-best-breakup-lines.html",
        "https://www.nytimes.com/2026/01/21/style/modern-love-what-are-your-dating-rules.html",
        "https://www.nytimes.com/2026/02/12/style/modern-dating-rules.html",
    )
}

# Bylines the paper omitted from the column itself and later ran as a correction.
# Keyed by canonical URL.
BYLINE_FIXES = {
    norm_url("https://www.nytimes.com/2005/11/13/fashion/sundaystyles/"
             "i-seemed-plucky-and-game-even-to-myself.html"): "Mindy Hung",
}


# Titles of the recurring non-essay features — reader solicitations and their
# crowdsourced round-ups — matched so *future* ones are caught automatically,
# without waiting to be added to EXCLUDE_URLS. Deliberately narrow (anchored
# imperatives / distinctive markers) so it never flags a real personal essay.
_NONESSAY_TITLE = re.compile(
    r"^tiny love stories\b"
    r"|^(tell us|we want|share your|send us|calling all)\b"
    r"|\bessay contest\b"
    r"|\bcrowdsourced\b"
    r"|^your \d+[- ]",
    re.I,
)


def is_nonessay(url: str, author: str, title: str = "") -> bool:
    """True for Modern Love *adjacent* content (the podcast, reader roundups,
    contest notices, calls for submissions) rather than the written column.
    Judged from the URL, byline, and title, so the check works at discovery,
    when re-validating an index row, and on future columns the curated
    EXCLUDE_URLS list hasn't seen yet."""
    u = (url or "").lower()
    author = (author or "").strip()
    al = author.lower()
    title = (title or "").strip()
    return (
        norm_url(url or "") in EXCLUDE_URLS
        or "/podcasts/" in u
        or "modern-love-podcast" in u
        or "podcast" in al
        or "new york times" in al            # institutional byline (roundups, calls)
        or author in PODCAST_BYLINES
        or bool(title and _NONESSAY_TITLE.search(title))
    )


def fixed_author(url: str, fallback: str = "") -> str:
    """The correct byline for a column whose author the paper omitted, else
    `fallback` (so callers can pass through whatever they already have)."""
    return BYLINE_FIXES.get(norm_url(url or ""), fallback)


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
