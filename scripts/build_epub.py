"""Bind the Markdown columns into a single EPUB with a per-column table of
contents, via pandoc.

    .venv/bin/python scripts/build_epub.py                 # all columns
    .venv/bin/python scripts/build_epub.py --out test.epub 2004-10-31-...  # subset
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import common

META = """\
---
title: Modern Love
subtitle: "The Complete New York Times Column"
creator:
- role: author
  text: The New York Times
language: en-US
description: >-
  A personal archive of the NYT Modern Love column, compiled from a paid
  subscription for offline reading.
---
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="specific slugs (default: all)")
    ap.add_argument("--out", default="modern-love.epub")
    ap.add_argument("--images", default=str(common.IMG_DIR),
                    help="directory of images to embed (default: data/images). "
                         "Point at a device-optimized set, e.g. data/images_epub.")
    args = ap.parse_args()

    if args.slugs:
        files = [common.MD_DIR / f"{s}.md" for s in args.slugs]
    else:
        files = sorted(common.MD_DIR.glob("*.md"))
    files = [f for f in files if f.exists()]
    if not files:
        print("no markdown files found — run extract.py first")
        return 1

    meta_path = common.DATA / "epub-meta.yaml"
    meta_path.write_text(META, encoding="utf-8")
    out = common.DATA / args.out

    cmd = [
        "pandoc",
        "--from=markdown",
        "--to=epub3",
        "--toc", "--toc-depth=1",
        "--split-level=1",
        f"--resource-path={args.images}",
        "--metadata-file", str(meta_path),
        "-o", str(out),
    ]
    cover = common.DATA / "cover.jpg"
    if cover.exists():
        cmd += [f"--epub-cover-image={cover}"]
    css = common.DATA / "epub.css"
    if css.exists():
        cmd += ["--css", str(css)]
    cmd += [str(f) for f in files]
    print(f"binding {len(files)} columns -> {out.name}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("pandoc failed:\n", r.stderr[-2000:])
        return 1

    size_mb = out.stat().st_size / 1e6
    print(f"OK  {out}  ({size_mb:.1f} MB, {len(files)} chapters)")
    if r.stderr.strip():
        print("pandoc notes:", r.stderr.strip()[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
