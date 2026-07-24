"""Bind the Markdown columns into EPUBs with a per-column table of contents,
via pandoc.

    .venv/bin/python scripts/build_epub.py                 # one omnibus
    .venv/bin/python scripts/build_epub.py --by-year       # one volume per year
    .venv/bin/python scripts/build_epub.py --by-year --year 2025 2026
    .venv/bin/python scripts/build_epub.py --out test.epub 2004-10-31-...  # subset
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import common

DESCRIPTION = """\
description: >-
  A personal archive of the NYT Modern Love column, compiled from a paid
  subscription for offline reading.
creator:
- role: author
  text: The New York Times
language: en-US"""


def meta_yaml(year: int | None) -> str:
    """The pandoc metadata block for one volume. A yearly volume puts the year
    in the title (23 shelf entries reading "Modern Love" are indistinguishable
    on a device) and carries belongs-to-collection/group-position so readers
    that understand series metadata shelve the set in order."""
    if year is None:
        head = ['title: Modern Love',
                'subtitle: "The Complete New York Times Column"']
    else:
        head = [f'title: "Modern Love {year}"',
                f'subtitle: "The New York Times Column, {year}"',
                'belongs-to-collection: Modern Love',
                f'group-position: {year}',
                f'date: "{year}"']
    return "---\n" + "\n".join(head) + "\n" + DESCRIPTION + "\n---\n"


def group_by_year(files: list[Path]) -> dict[int, list[Path]]:
    """Bucket column files by the year of their slug, oldest year first."""
    groups: dict[int, list[Path]] = {}
    for f in files:
        year = common.slug_year(f.name)
        if year is None:
            print(f"skipping {f.name}: no YYYY-MM-DD- prefix")
            continue
        groups.setdefault(year, []).append(f)
    return dict(sorted(groups.items()))


def build(files: list[Path], out: Path, images: str, year: int | None) -> bool:
    """Run pandoc over `files` into `out`. Returns True if the volume was written."""
    meta_path = common.DATA / "epub-meta.yaml"
    meta_path.write_text(meta_yaml(year), encoding="utf-8")

    cmd = [
        "pandoc",
        "--from=markdown",
        "--to=epub3",
        "--toc", "--toc-depth=1",
        "--split-level=1",
        f"--resource-path={images}",
        "--metadata-file", str(meta_path),
        "-o", str(out),
    ]
    cover = common.cover_path(year)
    if year is not None and not cover.exists():
        # Fall back rather than fail, but say so — 23 volumes behind one undated
        # cover is exactly the shelf you can't navigate.
        print(f"  no {cover.name}; using the omnibus cover "
              f"(run make_cover.py --all-years)")
        cover = common.cover_path(None)
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
        return False

    size_mb = out.stat().st_size / 1e6
    print(f"OK  {out}  ({size_mb:.1f} MB, {len(files)} chapters)")
    if r.stderr.strip():
        print("pandoc notes:", r.stderr.strip()[:500])
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="specific slugs (default: all)")
    ap.add_argument("--out", default="modern-love.epub",
                    help="omnibus filename; under --by-year its stem names each "
                         "volume (modern-love-2004.epub, ...)")
    ap.add_argument("--by-year", action="store_true",
                    help="write one EPUB per year instead of a single omnibus")
    ap.add_argument("--out-dir",
                    help="where --by-year volumes go (default: data/by-year)")
    ap.add_argument("--year", nargs="+", type=int, metavar="YYYY",
                    help="with --by-year, build only these years")
    ap.add_argument("--images", default=str(common.IMG_DIR),
                    help="directory of images to embed (default: data/images). "
                         "Point at a device-optimized set, e.g. data/images_epub.")
    args = ap.parse_args()

    if not args.by_year and (args.year or args.out_dir):
        ap.error("--year and --out-dir only apply with --by-year")

    if args.slugs:
        files = [common.MD_DIR / f"{s}.md" for s in args.slugs]
    else:
        files = sorted(common.MD_DIR.glob("*.md"))
    files = [f for f in files if f.exists()]
    if not files:
        print("no markdown files found — run extract.py first")
        return 1

    if not args.by_year:
        return 0 if build(files, common.DATA / args.out, args.images, None) else 1

    groups = group_by_year(files)
    if args.year:
        want = set(args.year)
        missing = sorted(want - set(groups))
        if missing:
            print(f"no columns for: {', '.join(map(str, missing))}")
        groups = {y: fs for y, fs in groups.items() if y in want}
    if not groups:
        print("nothing to bind")
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else common.DATA / "by-year"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.out).stem

    written, failed = [], []
    for year, group in groups.items():
        out = out_dir / f"{stem}-{year}.epub"
        (written if build(group, out, args.images, year) else failed).append(out)

    total_mb = sum(p.stat().st_size for p in written) / 1e6
    print(f"\n{len(written)} volumes -> {out_dir}  ({total_mb:.1f} MB total)")
    if failed:
        print(f"failed: {', '.join(p.name for p in failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
