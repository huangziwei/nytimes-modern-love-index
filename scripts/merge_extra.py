"""Merge a few recent columns that are missing from the third-party index.

The parser fix (parse_index.py) recovered the large 2005-06 and 2010-11 gaps
from the index itself. A handful of recent columns, though, are simply absent
from the index while present in NYT's own archive (see discover.py). These were
identified by diffing the archive against the parsed index within the remaining
audit gaps and keeping only genuine essays — excluding Tiny Love Stories,
podcasts, anniversary reprints, and video features. The Oct 2019 gap is left
open on purpose: it was the 15th-anniversary run of reprints, not new essays.
"""

from __future__ import annotations

import json
import re

import common

EXTRA = [
    "https://www.nytimes.com/2019/05/03/style/modern-love-sister-vanished.html",
    "https://www.nytimes.com/2019/05/10/style/modern-love-college-i-love-you-man-.html",
    "https://www.nytimes.com/2019/05/17/style/modern-love-college-hoarding-medical-leave.html",
    "https://www.nytimes.com/2019/05/24/style/modern-love-college-cant-hate-my-body-if-i-love-hers.html",
    "https://www.nytimes.com/2022/08/19/style/modern-love-cancer-last-act-of-intimate-kindness.html",
    "https://www.nytimes.com/2022/08/26/style/modern-love-lockdown-in-shanghai.html",
    "https://www.nytimes.com/2022/09/02/style/modern-love-i-broke-my-knee-which-fractured-my-marriage.html",
]
URL_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/([a-z]+)/([a-z0-9-]+)\.html")


def main() -> int:
    raw_path = common.DATA / "articles_raw.json"
    raw = json.loads(raw_path.read_text())
    have = {a["url"] for a in raw}
    added = 0
    for url in EXTRA:
        if url in have:
            continue
        y, m, d, section, slug = URL_RE.search(url).groups()
        raw.append({
            "title": slug.replace("modern-love-", "").replace("-", " ").title(),
            "url": url, "date": f"{y}-{m}-{d}", "section": section,
            "slug": f"{y}-{m}-{d}-{slug}"[:80], "image_url": None,
            "summary": None, "source": "archive-supplement",
        })
        added += 1
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    print(f"added {added} archive-supplement columns → {len(raw)} total in articles_raw.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
