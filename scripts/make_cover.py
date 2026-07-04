"""Render the book cover: League Spartan titling over a public-domain painting.

The artwork is Émile Friant's *Cast Shadows* (1891) — a couple outwardly
composed while their shadows lean into a kiss. It is in the public domain (CC0)
and fetched from Standard Ebooks' artwork collection. The cover is rendered at
the Kindle Scribe's native resolution (1860x2480, 3:4) so it fills the Scribe
and Colorsoft sleep screens with no letterbox, and written straight to JPEG by
Chromium (quality tuned so the painting stays clean at a sane ~0.5 MB).
"""

from __future__ import annotations

import base64

from playwright.sync_api import sync_playwright

import common

# Friant, "Cast Shadows" — public domain, via standardebooks.org/artworks.
ARTWORK_URL = "https://standardebooks.org/images/cover-uploads/2016.jpg"
ARTWORK = common.DATA / "artwork.jpg"
OUT = common.DATA / "cover.jpg"

W, H = 1860, 2480
TITLE_HTML = "MODERN<br>LOVE"
SUBTITLE_HTML = "THE&nbsp;COMPLETE<br>NEW&nbsp;YORK&nbsp;TIMES&nbsp;COLUMN"
DATE_HTML = "2004&ndash;2026"
JPEG_QUALITY = 50


def _data_uri(path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def build_html() -> str:
    art = _data_uri(ARTWORK, "image/jpeg")
    fonts = "\n".join(
        f'@font-face{{font-family:"LS";font-weight:{w};'
        f'src:url({_data_uri(common.FONTS_DIR / f"league-spartan-{w}.woff2", "font/woff2")}) '
        f'format("woff2")}}'
        for w in common.FONT_WEIGHTS
    )
    return f"""<style>
{fonts}
*{{margin:0;padding:0;box-sizing:border-box}}
.cover{{position:relative;width:{W}px;height:{H}px;overflow:hidden;background:#e9e2d6}}
.art{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 24%}}
.tblock{{position:absolute;top:5.5%;right:6.5%;width:max-content;text-align:right}}
.title{{font:900 172px/.82 'LS';letter-spacing:.01em;color:#241c16}}
.rule{{height:3px;width:210px;background:#241c16;opacity:.82;margin:46px 0 32px auto}}
.sub{{font:400 40px/1.4 'LS';letter-spacing:.14em;color:#2b231c}}
.date{{position:absolute;bottom:6%;left:3.2%;font:700 42px 'LS';letter-spacing:.26em;
  color:#e9dfcd;text-indent:.26em}}
</style>
<div class="cover"><img class="art" src="{art}">
  <div class="tblock">
    <div class="title">{TITLE_HTML}</div>
    <div class="rule"></div>
    <div class="sub">{SUBTITLE_HTML}</div>
  </div>
  <div class="date">{DATE_HTML}</div>
</div>"""


def main() -> int:
    common.DATA.mkdir(parents=True, exist_ok=True)
    common.ensure_fonts()
    if not ARTWORK.exists() or ARTWORK.stat().st_size < 10_000:
        print(f"downloading artwork from {ARTWORK_URL} …")
        ARTWORK.write_bytes(common.fetch_url(ARTWORK_URL))

    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        pg = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.set_content(build_html())
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(500)
        pg.locator(".cover").screenshot(path=str(OUT), type="jpeg", quality=JPEG_QUALITY)
        br.close()

    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
