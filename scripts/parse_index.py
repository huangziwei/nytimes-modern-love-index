"""Parse the Koski Modern Love index into a clean, de-duplicated article list.

Each `div.article` in the index carries the column's canonical URL, lead image,
title, and one-line summary. The byline and body come later from the article
page itself; here we only build the crawl work-list.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

import common

# Sections that are readable essays. `podcasts` are audio episodes (no text).
KEEP_SECTIONS = {"style", "fashion", "garden"}
URL_RE = re.compile(r"nytimes\.com/(\d{4})/(\d{2})/(\d{2})/([a-z]+)/([a-z0-9-]+)\.html")


def main() -> int:
    html = (common.DATA / "index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    seen: set[str] = set()
    articles: list[dict] = []
    dropped_podcast = 0

    for div in soup.select("div.article"):
        h3a = div.select_one("h3 a[href]")
        if not h3a:
            continue
        url = h3a["href"].split("?")[0]
        m = URL_RE.search(url)
        if not m:
            continue
        year, month, day, section, slug = m.groups()
        if section not in KEEP_SECTIONS:
            dropped_podcast += 1
            continue
        if url in seen:
            continue
        seen.add(url)

        img = div.select_one("amp-img[src], img[src]")
        summary = div.select_one("p.summary")
        articles.append(
            {
                "title": h3a.get_text(strip=True),
                "url": url,
                "date": f"{year}-{month}-{day}",
                "section": section,
                "slug": f"{year}-{month}-{day}-{slug}"[:80],
                "image_url": img["src"].split("?")[0] if img else None,
                "summary": summary.get_text(strip=True) if summary else None,
            }
        )

    articles.sort(key=lambda a: (a["date"], a["slug"]))
    out = common.DATA / "articles.json"
    out.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")

    by_year: dict[str, int] = {}
    with_img = 0
    for a in articles:
        by_year[a["date"][:4]] = by_year.get(a["date"][:4], 0) + 1
        with_img += bool(a["image_url"])

    print(f"kept {len(articles)} columns  ·  dropped {dropped_podcast} podcast/other")
    print(f"with lead image: {with_img}/{len(articles)}")
    print(f"span: {articles[0]['date']} … {articles[-1]['date']}")
    print("per year:", {k: by_year[k] for k in sorted(by_year)})
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
