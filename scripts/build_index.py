"""Generate the public, self-maintained column index into docs/.

Writes docs/index.json (+ docs/index.csv) — facts only: number, date, title,
author, URL — the data behind the GitHub Pages table. Titles and authors come
from the crawled pages where we have them (falling back to the source index
title with a blank author for columns not yet fetched), so the index fills in
and stays accurate as the crawl proceeds. This is bibliographic metadata, not
essay text, and is committed to the repo so the project no longer depends on a
third-party index staying online.
"""

from __future__ import annotations

import csv
import json
import re

import common

BYLINE = re.compile(r":::\s*byline\s*\nBy (.+?)(?: · |\n)")
TITLE = re.compile(r"#\s+(.+)")


def crawled_meta() -> dict[str, tuple[str | None, str]]:
    """Map article URL -> (real headline, author) from extracted Markdown,
    honoring rename.py's slugs when present."""
    fmap = common.DATA / "filename_map.json"
    if fmap.exists():
        pairs = [(slug, info["url"]) for slug, info in json.loads(fmap.read_text()).items()]
    else:
        pairs = [(a["slug"], a["url"])
                 for a in json.loads((common.DATA / "articles.json").read_text())]
    out: dict[str, tuple[str | None, str]] = {}
    for slug, url in pairs:
        md = common.MD_DIR / f"{slug}.md"
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8")
        tm, bm = TITLE.match(text), BYLINE.search(text)
        out[url] = (tm.group(1).strip() if tm else None, bm.group(1).strip() if bm else "")
    return out


def main() -> int:
    articles = json.loads((common.DATA / "articles.json").read_text())
    articles.sort(key=lambda a: (a["date"], a["slug"]))
    meta = crawled_meta()

    rows = []
    for n, a in enumerate(articles, 1):
        title, author = meta.get(a["url"], (None, ""))
        rows.append({
            "n": n,
            "date": a["date"],
            "title": title or a.get("title") or "",
            "author": author,
            "url": a["url"],
        })

    docs = common.ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    with (docs / "index.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["n", "date", "title", "author", "url"])
        w.writeheader()
        w.writerows(rows)

    with_author = sum(1 for r in rows if r["author"])
    print(f"wrote docs/index.json — {len(rows)} columns, {with_author} with author")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
