"""Rename deduped columns from URL slugs to headline-derived slugs.

For the ~160 early essays whose only NYT URL is a `DDlove` short-code, the URL
slug is non-descriptive. Each file's real headline is on its `# ` title line, so
we rebuild the name as `<date>-<slugified-title>`, carrying the image files and
their in-text references along. A `<new-slug> -> source URL` map is written to
filename_map.json so any file still traces back to its NYT origin.

Run after dedup.py and before build_epub.py.  `--dry-run` previews only.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

import common

INDEX = {a["slug"]: a for a in json.loads((common.DATA / "articles.json").read_text())}


def slugify(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = re.sub(r"['’`]", "", t)                  # "won't" -> "wont"
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return re.sub(r"-{2,}", "-", t)[:70].strip("-")


def main() -> int:
    dry = "--dry-run" in sys.argv
    used: set[str] = set()
    mapping: dict[str, dict] = {}
    renamed = 0

    for f in sorted(common.MD_DIR.glob("*.md")):
        old = f.stem
        text = f.read_text()
        m = re.match(r"#\s+(.+)", text)
        title = m.group(1).strip() if m else old
        date = old[:10] if re.match(r"\d{4}-\d{2}-\d{2}", old) else ""
        base = f"{date}-{slugify(title)}" if date else slugify(title)

        new, i = base, 2
        while new in used:
            new, i = f"{base}-{i}", i + 1
        used.add(new)

        src = INDEX.get(old, {})
        mapping[new] = {"url": src.get("url"), "old_slug": old, "title": title}
        if new == old:
            continue
        renamed += 1
        if dry:
            print(f"  {old}  ->  {new}")
            continue

        new_text = text
        for img in sorted(common.IMG_DIR.glob(f"{old}-*")):
            suffix = img.name[len(old):]              # e.g. "-1.jpg"
            new_text = new_text.replace(f"({img.name})", f"({new}{suffix})")
            img.rename(common.IMG_DIR / f"{new}{suffix}")
        (common.MD_DIR / f"{new}.md").write_text(new_text, encoding="utf-8")
        f.unlink()

    if not dry:
        (common.DATA / "filename_map.json").write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'would rename' if dry else 'renamed'} {renamed} files "
          f"(of {len(mapping)}); map -> filename_map.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
