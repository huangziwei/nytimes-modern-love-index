"""Crawl article HTML with the logged-in, headed browser.

Resumable (skips pages already saved), rate-limited, and self-defending: if a
run of pages comes back gated or blocked, it stops rather than silently saving a
thousand truncated shells (the usual sign the login expired).

    .venv/bin/python scripts/fetch.py                 # everything outstanding
    .venv/bin/python scripts/fetch.py --limit 5       # first 5 (test batch)
    .venv/bin/python scripts/fetch.py --slugs a,b,c   # specific slugs
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time

from playwright.sync_api import sync_playwright

import common

MIN_BYTES = 50_000        # a real article page is 300 KB+; a block page is < 2 KB
MIN_PARAGRAPHS = 6        # fewer than this ⇒ gated/truncated/blocked
ABORT_AFTER = 6           # consecutive suspect pages ⇒ stop (session likely dead)


def is_good(html: str) -> bool:
    return len(html) >= MIN_BYTES and html.count('"ParagraphBlock"') >= MIN_PARAGRAPHS


def already_have(slug: str) -> bool:
    f = common.HTML_DIR / f"{slug}.html"
    return f.exists() and f.stat().st_size >= MIN_BYTES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--slugs", type=str, default="")
    ap.add_argument("--min-delay", type=float, default=2.0)
    ap.add_argument("--max-delay", type=float, default=4.5)
    ap.add_argument("--force", action="store_true", help="re-fetch even if present")
    args = ap.parse_args()

    common.HTML_DIR.mkdir(parents=True, exist_ok=True)
    articles = json.loads((common.DATA / "articles.json").read_text())

    if args.slugs:
        wanted = set(args.slugs.split(","))
        articles = [a for a in articles if a["slug"] in wanted]
    todo = [a for a in articles if args.force or not already_have(a["slug"])]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(todo)} to fetch (of {len(articles)} selected)")
    if not todo:
        return 0

    saved = suspect = 0
    consecutive = 0
    failures: list[dict] = []

    with sync_playwright() as p:
        ctx = common.make_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("Warming up on homepage …", "status", common.warmup(page))

        for i, a in enumerate(todo, 1):
            slug = a["slug"]
            try:
                resp = common.load_article(page, a["url"])
                status = resp.status if resp else None
                html = page.content()
            except Exception as e:  # noqa: BLE001
                status, html = None, ""
                print(f"[{i}/{len(todo)}] ERR {slug}: {type(e).__name__}")

            good = bool(status == 200 and is_good(html))
            if good:
                (common.HTML_DIR / f"{slug}.html").write_text(html, encoding="utf-8")
                saved += 1
                consecutive = 0
                pblocks = html.count('"ParagraphBlock"')
                print(f"[{i}/{len(todo)}] ok  {slug}  ({len(html)//1024}KB, {pblocks}p)")
            else:
                suspect += 1
                consecutive += 1
                failures.append({"slug": slug, "url": a["url"], "status": status,
                                  "bytes": len(html), "pblocks": html.count('"ParagraphBlock"')})
                print(f"[{i}/{len(todo)}] SUSPECT {slug} status={status} "
                      f"bytes={len(html)} (consecutive={consecutive})")
                if consecutive >= ABORT_AFTER:
                    print(f"\nAborting: {consecutive} suspect pages in a row — "
                          f"login likely expired. Re-run scripts/login.py.")
                    break

            time.sleep(random.uniform(args.min_delay, args.max_delay))

        ctx.close()

    if failures:
        (common.DATA / "failures.json").write_text(json.dumps(failures, indent=2))
    print(f"\nsaved={saved}  suspect={suspect}  (failures logged: {len(failures)})")
    return 0 if saved and not (suspect and saved == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
