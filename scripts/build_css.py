"""Generate data/epub.css: Standard Ebooks reading conventions adapted to
pandoc's EPUB output, with League Spartan embedded (base64) for titling.

SE conventions borrowed: justified text with automatic hyphenation, no
hyphenation in headings, `p{margin:0}` with first-line indents on runs of
paragraphs (first paragraph after a heading stays flush), tight header spacing.
League Spartan (SE's house titling face, also on the cover) sets the chapter
titles and bylines; the body stays in the reader's serif so the reader keeps
control of the reading face.
"""

from __future__ import annotations

import base64

import common

FONTS = common.DATA / "fonts"


def face(weight: int) -> str:
    data = (FONTS / f"league-spartan-{weight}.woff2").read_bytes()
    b64 = base64.b64encode(data).decode()
    return (f'@font-face{{font-family:"League Spartan";font-weight:{weight};'
            f'font-style:normal;font-display:swap;'
            f'src:url(data:font/woff2;base64,{b64}) format("woff2")}}')


CSS = """
{faces}

:root{{ --muted:#6b6b6b; }}

html{{ -webkit-hyphens:auto; -epub-hyphens:auto; hyphens:auto; }}

body{{
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,"Times New Roman",serif;
  line-height:1.5;
  text-align:justify;
  -webkit-hyphens:auto; -epub-hyphens:auto; hyphens:auto;
  margin:0;
  padding:0 5%;
  widows:2; orphans:2;
}}

/* Continuous prose: no inter-paragraph space, indent every paragraph after the
   first in a run. A paragraph that opens a chapter or follows an image/heading
   is not preceded by a <p>, so it stays flush — the book-typography default. */
p{{ margin:0; text-indent:0; }}
p + p{{ text-indent:1.15em; }}

/* Chapter title (the essay headline) in League Spartan, never hyphenated. */
h1{{
  font-family:"League Spartan","Helvetica Neue",Arial,sans-serif;
  font-weight:900;
  font-size:1.55em;
  line-height:1.08;
  letter-spacing:.005em;
  text-align:left;
  text-indent:0;
  -webkit-hyphens:none; hyphens:none;
  text-wrap:balance;
  margin:1.4em 0 0;
  page-break-after:avoid; break-after:avoid;
}}

/* Byline ("By Author · Date"): small League Spartan caps, muted. */
.byline{{ margin:.7em 0 1.9em; }}
.byline p{{
  font-family:"League Spartan","Helvetica Neue",Arial,sans-serif;
  font-weight:400;
  font-size:.76em;
  letter-spacing:.14em;
  text-transform:uppercase;
  text-align:left;
  text-indent:0;
  color:var(--muted);
  -webkit-hyphens:none; hyphens:none;
}}

/* Images: centred, never larger than the page, kept whole across breaks. */
img{{ max-width:100%; height:auto; }}
p > img{{ display:block; margin:1.5em auto; }}
figure{{ margin:1.5em 0; text-align:center; page-break-inside:avoid; break-inside:avoid; }}
figcaption{{ font-size:.8em; font-style:italic; color:var(--muted); margin-top:.4em; }}

blockquote{{ margin:1em 1.6em; font-style:italic; }}
em{{ font-style:italic; }}
strong{{ font-weight:700; }}
a{{ color:inherit; text-decoration:none; }}

/* Pandoc's generated title page, kept consistent with the cover. */
h1.title,.title{{ font-family:"League Spartan",sans-serif; font-weight:900; }}
p.author,.author,.subtitle{{ font-family:"League Spartan",sans-serif; font-weight:400;
  letter-spacing:.1em; text-transform:uppercase; }}
"""


def main() -> int:
    css = CSS.format(faces="\n".join(face(w) for w in (400, 700, 900)))
    out = common.DATA / "epub.css"
    out.write_text(css.strip() + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, fonts embedded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
