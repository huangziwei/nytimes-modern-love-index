"""Prune provably-safe alias URLs from the crawl work-list.

NYT published many 2005-2008 essays under a short `DDlove` URL *and* a
descriptive one on the same date; the index lists both. Where a descriptive
sibling exists, the `DDlove` entry is a pure alias and can be dropped before we
ever fetch it (the essay survives under its descriptive URL). Alias-only dates
(no descriptive sibling) are kept — there the short slug IS canonical.

This is lossless by construction and only removes same-date aliases. Non-obvious
duplicates (title-variant slugs, e.g. `x-modern-love` vs `modern-love-x`) are
left for the content-based `dedup.py` pass, which compares actual body text.
"""

from __future__ import annotations

import collections
import json
import re

import common

ALIAS = re.compile(r"^(modern-love-)?\d{1,2}love$")


def is_alias(slug: str) -> bool:
    return bool(ALIAS.match(slug[11:]))  # slug[11:] drops the YYYY-MM-DD- prefix


def main() -> int:
    # articles_raw.json is the pristine full list (parse_index + merge_extra);
    # this derives the pruned work-list into articles.json.
    raw_path = common.DATA / "articles_raw.json"
    work_path = common.DATA / "articles.json"
    articles = json.loads(raw_path.read_text())

    by_date = collections.defaultdict(list)
    for a in articles:
        by_date[a["date"]].append(a)

    drop: set[str] = set()
    for date, group in by_date.items():
        has_descriptive = any(not is_alias(a["slug"]) for a in group)
        if has_descriptive:
            for a in group:
                if is_alias(a["slug"]):
                    drop.add(a["slug"])

    # Modern Love Podcast episodes carry the column's kicker and were crawled as
    # if columns, but they're audio, not the written essay — drop them entirely.
    podcasts = {a["slug"] for a in articles if common.is_nonessay(a["url"], "")}

    remove = drop | podcasts
    kept = [a for a in articles if a["slug"] not in remove]
    work_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2))

    # Remove any already-fetched copies of the pruned entries.
    removed_files = 0
    for slug in remove:
        for p in (common.HTML_DIR / f"{slug}.html", common.MD_DIR / f"{slug}.md"):
            if p.exists():
                p.unlink()
                removed_files += 1

    print(f"pruned {len(drop)} same-date aliases + {len(podcasts)} podcast episodes")
    print(f"work-list: {len(articles)} -> {len(kept)} entries")
    print(f"deleted {removed_files} already-fetched files")
    if podcasts:
        print("sample podcasts:", sorted(podcasts)[:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
