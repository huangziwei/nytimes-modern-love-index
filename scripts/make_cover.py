"""Render the book covers: League Spartan titling over a public-domain painting.

The artwork is Émile Friant's *Cast Shadows* (1891) — a couple outwardly
composed while their shadows lean into a kiss. It is in the public domain (CC0)
and fetched from Standard Ebooks' artwork collection. Covers are rendered at the
Kindle Scribe's native resolution (1860x2480, 3:4) so they fill the Scribe and
Colorsoft sleep screens with no letterbox, and written straight to JPEG by
Chromium (quality tuned so the painting stays clean at a sane ~0.5 MB).

    .venv/bin/python scripts/make_cover.py              # omnibus -> data/cover.jpg
    .venv/bin/python scripts/make_cover.py --all-years  # -> data/covers/cover-YYYY.jpg
    .venv/bin/python scripts/make_cover.py --year 2025 2026
"""

from __future__ import annotations

import argparse
import base64

from playwright.sync_api import sync_playwright

import common

# Friant, "Cast Shadows" — public domain, via standardebooks.org/artworks.
ARTWORK_URL = "https://standardebooks.org/images/cover-uploads/2016.jpg"
ARTWORK = common.DATA / "artwork.jpg"

W, H = 1860, 2480
TITLE_HTML = "MODERN<br>LOVE"
SUBTITLE_OMNIBUS = "THE&nbsp;COMPLETE<br>NEW&nbsp;YORK&nbsp;TIMES&nbsp;COLUMN"
SUBTITLE_YEAR = "THE&nbsp;NEW&nbsp;YORK&nbsp;TIMES&nbsp;COLUMN"
DATE_OMNIBUS = "2004&ndash;2026"
JPEG_QUALITY = 50


def _data_uri(path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def build_html(year: int | None = None) -> str:
    """The cover markup for one volume.

    The omnibus keeps the run's span in the quiet bottom corner. A yearly volume
    instead lifts its year into the title block at near-title size, and drops
    "COMPLETE" from the subtitle since one year isn't the whole run. The corner
    treatment is what a shelf of 23 volumes has to be told apart by, and at
    thumbnail scale it collapses to a few unreadable pixels."""
    art = _data_uri(ARTWORK, "image/jpeg")
    fonts = "\n".join(
        f'@font-face{{font-family:"LS";font-weight:{w};'
        f'src:url({_data_uri(common.FONTS_DIR / f"league-spartan-{w}.woff2", "font/woff2")}) '
        f'format("woff2")}}'
        for w in common.FONT_WEIGHTS
    )
    if year is None:
        stamp = f'<div class="sub">{SUBTITLE_OMNIBUS}</div>'
        corner = f'<div class="date">{DATE_OMNIBUS}</div>'
    else:
        stamp = (f'<div class="year">{year}</div>'
                 f'<div class="sub sub-year">{SUBTITLE_YEAR}</div>')
        corner = ""
    return f"""<style>
{fonts}
*{{margin:0;padding:0;box-sizing:border-box}}
.cover{{position:relative;width:{W}px;height:{H}px;overflow:hidden;background:#e9e2d6}}
.art{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 24%}}
.tblock{{position:absolute;top:5.5%;right:6.5%;width:max-content;text-align:right}}
.title{{font:900 172px/.82 'LS';letter-spacing:.01em;color:#241c16}}
.rule{{height:3px;width:210px;background:#241c16;opacity:.82;margin:46px 0 32px auto}}
.sub{{font:400 40px/1.4 'LS';letter-spacing:.14em;color:#2b231c}}
.year{{font:900 200px/.9 'LS';letter-spacing:.02em;color:#241c16;margin-top:14px}}
.sub-year{{font-size:34px;letter-spacing:.16em;margin-top:18px}}
.date{{position:absolute;bottom:6%;left:3.2%;font:700 42px 'LS';letter-spacing:.26em;
  color:#e9dfcd;text-indent:.26em}}
</style>
<div class="cover"><img class="art" src="{art}">
  <div class="tblock">
    <div class="title">{TITLE_HTML}</div>
    <div class="rule"></div>
    {stamp}
  </div>
  {corner}
</div>"""


def column_years() -> list[int]:
    """Every year the archive has columns for, oldest first."""
    years = {common.slug_year(f.name) for f in common.MD_DIR.glob("*.md")}
    return sorted(y for y in years if y is not None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", nargs="+", type=int, metavar="YYYY",
                    help="render per-year covers into data/covers")
    ap.add_argument("--all-years", action="store_true",
                    help="render a cover for every year present in data/markdown")
    args = ap.parse_args()

    if args.all_years:
        years = column_years()
        if not years:
            print("no dated columns found — run extract.py first")
            return 1
    else:
        years = sorted(set(args.year)) if args.year else [None]

    common.DATA.mkdir(parents=True, exist_ok=True)
    common.ensure_fonts()
    if not ARTWORK.exists() or ARTWORK.stat().st_size < 10_000:
        print(f"downloading artwork from {ARTWORK_URL} …")
        ARTWORK.write_bytes(common.fetch_url(ARTWORK_URL))
    if any(y is not None for y in years):
        common.COVERS_DIR.mkdir(parents=True, exist_ok=True)

    # One browser for the whole set — relaunching per year dominates the runtime.
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        pg = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for year in years:
            out = common.cover_path(year)
            pg.set_content(build_html(year))
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(500)
            pg.locator(".cover").screenshot(path=str(out), type="jpeg",
                                            quality=JPEG_QUALITY)
            print(f"wrote {out} ({out.stat().st_size // 1024} KB, {W}x{H})")
        br.close()

    if len(years) > 1:
        print(f"{len(years)} covers -> {common.COVERS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
