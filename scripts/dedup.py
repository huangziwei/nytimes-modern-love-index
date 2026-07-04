"""Collapse alias-duplicate columns by comparing actual body text.

Two markdown files with an identical normalized body are the same essay reached
through different NYT URLs; we keep one canonical file and delete the rest.
Distinct essays that merely share a publish date (themed feature packages) have
different bodies and are all preserved.

Canonical pick: prefer a descriptive slug over a `DDlove` short-code, then the
one with the most title words. The chosen slug only names the file — the EPUB
chapter uses the essay's own headline — so the choice is purely cosmetic.

Run after extract.py and before build_epub.py.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re

import common

_ALIAS = re.compile(r"^(modern-love-)?\d{1,2}love$")


def fingerprint(md_text: str) -> str:
    body = [ln for ln in md_text.splitlines()
            if ln.strip() and not ln.startswith(("#", "!"))]
    norm = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", " ".join(body))  # flatten links
    norm = re.sub(r"\s+", " ", norm).strip().lower()
    return hashlib.sha1(norm.encode()).hexdigest()


def canonical_rank(slug: str) -> tuple:
    rest = slug[11:] if len(slug) > 11 else slug
    is_alias = bool(_ALIAS.match(rest))
    words = len(re.findall(r"[a-z]{3,}", rest))
    return (is_alias, -words, -len(rest))  # non-alias, more words, longer


def main() -> int:
    files = sorted(common.MD_DIR.glob("*.md"))
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for f in files:
        groups[fingerprint(f.read_text())].append(f.stem)

    report, dropped = [], []
    for slugs in groups.values():
        if len(slugs) == 1:
            continue
        canonical = min(slugs, key=canonical_rank)
        aliases = [s for s in slugs if s != canonical]
        report.append({"canonical": canonical, "aliases": aliases})
        for s in aliases:
            (common.MD_DIR / f"{s}.md").unlink(missing_ok=True)
            dropped.append(s)

    (common.DATA / "duplicates.json").write_text(json.dumps(report, indent=2))
    print(f"{len(files)} files -> {len(groups)} unique essays "
          f"({len(dropped)} alias copies removed)")
    if report:
        big = max(report, key=lambda r: len(r["aliases"]))
        print(f"largest alias group: {big['canonical']}  +{len(big['aliases'])} copies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
