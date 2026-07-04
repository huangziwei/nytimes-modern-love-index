"""Interactive, one-time NYT login.

Run this yourself from the shell (so you can type into the browser and the
terminal):

    PLAYWRIGHT_BROWSERS_PATH="$PWD/.pw-browsers" .venv/bin/python scripts/login.py

A Chromium window opens on the NYT homepage. Click "Log In" (top-right), sign in
with your subscriber account, solve any challenge, then return here and press
Enter. The session is stored in ./.pw-profile and reused by the crawler; you
won't need to log in again unless it expires.
"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

import common

# A recent Modern Love column used only to confirm full-text access after login.
VERIFY_URL = (
    "https://www.nytimes.com/2026/06/19/style/i-have-fallen-in-love-with-my-doctor.html"
)


def subscription_markers(html: str) -> dict:
    """Booleans that indicate the session is an entitled subscriber (no content
    is printed — only the flags and a paragraph count)."""
    out = {}
    for key in ("isSubscriber", "hasCompleteAccess", "hasFullAccess"):
        m = re.search(rf'"{key}":(true|false)', html)
        out[key] = m.group(1) if m else "—"
    out["ParagraphBlocks"] = html.count('"ParagraphBlock"')
    return out


def main() -> int:
    with sync_playwright() as p:
        ctx = common.make_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("Opening nytimes.com …")
        common.warmup(page)
        print("\n" + "=" * 64)
        print("  1. In the browser window, click 'Log In' (top-right).")
        print("  2. Sign in with your NYT subscriber account.")
        print("  3. Solve any 'press & hold' / captcha challenge if shown.")
        print("  4. Come back here and press Enter.")
        print("=" * 64)
        try:
            input("\nPress Enter once you are logged in… ")
        except EOFError:
            print("No interactive stdin. Run this script yourself with the `!` "
                  "prefix or from a terminal.", file=sys.stderr)
            ctx.close()
            return 2

        # Confirm full-text access on a known column.
        print("\nVerifying subscriber access …")
        resp = common.load_article(page, VERIFY_URL)
        html = page.content()
        status = resp.status if resp else None
        names = sorted({c["name"] for c in ctx.cookies()})
        auth_like = [n for n in names if re.search(r"(?i)nyt-?s|sidny|nyt-?auth|nyt-?mps|jkidd", n)]

        # Persist a storage-state backup alongside the on-disk profile.
        ctx.storage_state(path=str(common.DATA / "state.json"))
        ctx.close()

    print(f"  article status : {status}")
    print(f"  markers        : {subscription_markers(html)}")
    print(f"  auth cookies   : {auth_like}")
    ok = status == 200 and subscription_markers(html)["ParagraphBlocks"] > 5
    print("\nLOGIN_OK — session saved to .pw-profile + data/state.json" if ok
          else "\nLOGIN_UNVERIFIED — check the browser and re-run if needed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
