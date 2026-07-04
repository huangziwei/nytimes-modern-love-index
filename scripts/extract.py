"""Turn saved article HTML into clean Markdown + downloaded images.

NYT renders the essay into the DOM under `<section name="articleBody">`, with the
byline and publish date in stable `<meta>` tags. We walk the body in document
order, emitting paragraphs, sub-headings, and figures (with captions), and pull
each referenced image from NYT's open CDN.
"""

from __future__ import annotations

import json
import re
import struct
import sys
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

import common

UA = {"User-Agent": common.UA}
INDEX = {a["slug"]: a for a in json.loads((common.DATA / "articles.json").read_text())}

# NYT's own promo/submission/social furniture that lives inside the article body
# but isn't the essay. Matched case-insensitively against a whole paragraph.
_PROMO = re.compile(
    r"sign up for love letter"
    r"|our weekly email about modern love"
    r"|^want more from modern love"
    r"|^want more\?"
    r"|to find previous modern love"
    r"|to submit a modern love essay"
    r"|modern love can be reached"
    r"|tiny love stories"              # separate NYT product cross-promo
    r"|/newsletters/love-letter"       # inline newsletter sign-up link
    r"|for the podcast, essays and more, visit"
    r"|to hear modern love"            # podcast plug (footer)
    r"|modern love: the podcast"       # podcast name (top/footer plugs)
    r"|hear this essay read"           # "hear this essay read by <celebrity>"
    r"|you can now hear this essay"
    r"|read this essay on"
    r"|continue following our fashion"  # social-follow plug
    r"|to read past modern love columns"
    r"|modernlove@nytimes\.com"        # submission email
    r"|e-?mail:\s*modernlove"
    # editorial prefaces prepended to reprints / anniversary features
    r"|to celebrate modern love"
    r"|this week we present"
    r"|series of special features"
    r"|adapted for the television series"
    r"|editor['’]?s?['’]? note"
    r"|this essay is part of"
    # editorial correction notes (top banner + dated footer)
    r"|correction appended"
    r"|^correction[s]?:"
    r"|an earlier version of this",
    re.I,
)

# Standalone furniture labels that appear as their own paragraph.
_LABELS = re.compile(r"^(advertisement|modern love)$", re.I)

# Bio verbs that follow the author's name in a third-person end-of-essay bio.
_BIO_VERB = re.compile(
    r"\b(is|was)\s+(a|an|the|now|currently|working|writing|based)\b"
    r"|is the (author|editor|writer)\b|author of\b|lives? (in|near|with|outside)\b"
    r"|based in\b|teaches\b|\bwww\.|\.com\b|\bblog\b|led to a book"
    r"|['’]s (first|latest|debut|memoir|novel|book|essay)\b",
    re.I,
)


def _flatten_links(text: str) -> str:
    """`[label](url)` -> `label`, so a bio opening with a linked author name
    (`[Nicole Walker](https://…), who teaches …`) still starts with the name."""
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)


def is_boilerplate(text: str) -> bool:
    return bool(_PROMO.search(text)) or bool(_LABELS.match(text.strip("*_ `")))


def is_author_bio(text: str, author: str | None) -> bool:
    """A trailing paragraph that opens with the author's name in the third
    person (essays are first-person) and reads like a contributor bio."""
    if not author:
        return False
    probe = re.sub(r"[*_`]", "", _flatten_links(text)).strip()
    probe = re.sub(r"^MODERN LOVE\s*", "", probe, flags=re.I).strip()
    names = author.split()
    first, last = re.escape(names[0]), re.escape(names[-1])
    starts_name = re.match(rf"^{re.escape(author)}\b", probe) or re.match(
        rf"^{first}\b.{{0,40}}?\b{last}\b", probe)
    return bool(starts_name and _BIO_VERB.search(probe))


# ---- image download -------------------------------------------------------

# NYT serves every master image in a family of named renditions. The article
# index and NYT's lazy `<img src>` usually point at a ~190px *square* thumbnail
# (`filmstrip`, `thumbWide`, `thumbStandard`); the full-resolution master is
# `superJumbo` (long side up to 2048px), with `jumbo`/`articleLarge` as smaller
# fallbacks. Each rendition is versioned independently, so `foo-filmstrip-v3`
# can pair with `foo-superJumbo-v2` — or an unversioned `foo-superJumbo` — which
# is why we probe a short list of version suffixes per rendition.
_REND_RE = re.compile(
    r"-(?:superJumbo|jumbo|master\d+|articleLarge|articleInline|thumbWide"
    r"|thumbStandard|thumbLarge|filmstrip|mediumThreeByTwo\d+|mediumSquare\d+"
    r"|square\d+|blog\d+|popup|sfSpan|hpMedium|hpLarge|moth|videoLarge|slide"
    r"|xlarge|inline)(-v\d+)?(\.\w+)$"
)

# Long side (px) at or above which a file is already a full-res rendition, so a
# re-run can skip re-downloading it.
_HI_RES_MIN = 1000


def _dims(data: bytes) -> tuple[int, int] | None:
    """(width, height) read from a JPEG or PNG header, or None if unparsable."""
    if data[:2] == b"\xff\xd8":                       # JPEG: scan to a frame header
        i, n = 2, len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":              # PNG: IHDR sits at a fixed offset
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    return None


def _download(url: str) -> bytes | None:
    """GET an image URL; return its bytes only if it's a real, non-trivial image
    (a 404 hands back an HTML error page, which this rejects)."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.headers.get_content_maintype() != "image":
                return None
            data = r.read()
    except Exception:  # noqa: BLE001
        return None
    return data if len(data) > 3000 and _dims(data) else None


def _hi_res_candidates(url: str) -> list[str]:
    """Higher-resolution variants of an NYT image URL, largest first.

    Empty when the URL carries no recognizable rendition token (very old
    flat-style paths like `.../04love190.1.jpg`, which have no larger master)."""
    base = url.split("?")[0]
    m = _REND_RE.search(base)
    if not m:
        return []
    ver, ext = m.group(1) or "", m.group(2)
    out, seen = [], set()
    for rend in ("superJumbo", "jumbo", "articleLarge"):
        for v in (ver, "", "-v2", "-v3", "-v4"):
            cand = _REND_RE.sub(f"-{rend}{v}{ext}", base)
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


def img_identity(url: str) -> str:
    """Rendition-independent key for an NYT image, so the same illustration
    reaching us as both the index thumbnail and an in-body figure de-dupes to a
    single download."""
    parts = url.split("?")[0].rstrip("/").split("/")
    stem = _REND_RE.sub("", parts[-1])
    stem = re.sub(r"\.(jpg|jpeg|png|webp|gif)$", "", stem, flags=re.I)
    parent = parts[-2] if len(parts) >= 2 else ""
    return f"{parent}/{stem}"


def figure_src(fig: Tag) -> str | None:
    """Best image URL inside a <figure>: the widest `srcset` entry across its
    <img>/<source> tags (NYT lazy-loads the real image there), else `<img src>`.
    None for figures carrying no image, e.g. the audio player on recent essays."""
    best_url, best_w = None, -1
    for tag in fig.find_all(("img", "source")):
        for part in (tag.get("srcset") or "").split(","):
            bits = part.split()
            if not bits:
                continue
            w = (int(bits[1][:-1]) if len(bits) > 1
                 and bits[1].endswith("w") and bits[1][:-1].isdigit() else 0)
            if w > best_w:
                best_url, best_w = bits[0], w
    if best_url:
        return best_url
    img = fig.find("img")
    return (img.get("src") or None) if img else None


def fetch_image(url: str, slug: str, n: int) -> str | None:
    """Download one image at the best resolution NYT offers; return its local
    filename (or None on failure).

    We try the `superJumbo`/`jumbo` renditions ahead of the URL as given, so the
    index's square thumbnails are replaced by the full-size master."""
    if not url:
        return None
    ext = Path(url.split("?")[0]).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    name = f"{slug}-{n}{ext}"
    dest = common.IMG_DIR / name
    if dest.exists():
        d = _dims(dest.read_bytes())
        if d and max(d) >= _HI_RES_MIN:
            return name
    for cand in _hi_res_candidates(url) + [url.split("?")[0]]:
        data = _download(cand)
        if data:
            dest.write_bytes(data)
            return name
    return None


# ---- inline markdown ------------------------------------------------------

def inline(node: Tag) -> str:
    parts: list[str] = []
    for c in node.children:
        if isinstance(c, NavigableString):
            parts.append(str(c))
        elif isinstance(c, Tag):
            if c.name in ("em", "i", "strong", "b"):
                # Empty/whitespace-only emphasis tags (NYT CMS artifacts) must
                # not emit markers, or adjacent ones collide into `****`. Keep a
                # space if the tag held one so words don't fuse.
                inner = inline(c)
                mark = "*" if c.name in ("em", "i") else "**"
                parts.append(f"{mark}{inner}{mark}" if inner
                             else (" " if c.get_text() else ""))
            elif c.name == "a":
                txt = inline(c)
                href = c.get("href", "")
                parts.append(f"[{txt}]({href})" if href else txt)
            elif c.name == "br":
                parts.append("\n")
            else:
                parts.append(inline(c))
    s = re.sub(r"\*{4,}", "", "".join(parts))     # merge colliding bold runs
    return re.sub(r"[ \t]{2,}", " ", s).strip()   # tidy doubled spaces


def clean_caption(cap_el: Tag | None) -> str:
    """Figure caption with the NYT image credit removed.

    Credits render as `Credit...<name>` (photographer/illustrator attribution) —
    noise on the page and doubly so for TTS. We drop the credit and everything
    after it, keeping any real descriptive caption that precedes it."""
    if cap_el is None:
        return ""
    txt = inline(cap_el)
    txt = re.split(r"Credit\s*(?:\.{2,}|…|\.\.\.)", txt, flags=re.I)[0].strip()
    return txt if re.search(r"[A-Za-z0-9]", txt) else ""


# ---- meta -----------------------------------------------------------------

def meta(soup: BeautifulSoup, **kw) -> str | None:
    tag = soup.find("meta", attrs=kw)
    return tag.get("content") if tag and tag.get("content") else None


def extract_one(slug: str) -> dict | None:
    html = (common.HTML_DIR / f"{slug}.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    idx = INDEX.get(slug, {})

    h1 = soup.find("h1")
    title = (h1.get_text(strip=True) if h1 else None) or meta(
        soup, property="og:title") or idx.get("title") or slug
    byl = meta(soup, name="byl")
    author = (byl or "").removeprefix("By ").strip() or None
    author = author or common.fixed_author(idx.get("url", "")) or None
    # Prefer the index/URL date (original publication) over the page's
    # published_time, which reprints overwrite with the re-publish date.
    published = meta(soup, property="article:published_time")
    date = (idx.get("date") or published or "")[:10]

    body = soup.find("section", attrs={"name": "articleBody"}) or soup.find("article")
    if body is None:
        return None

    # Delete injection slots before extracting: Dropzones carry "Advertisement"
    # labels and injected modules; AudioBlocks add a spurious "Listen:" heading.
    # The essay itself lives in StoryBodyCompanionColumn, never in these.
    for w in body.select('[data-testid^="Dropzone"], [data-testid^="AudioBlock"], '
                         '[data-testid^="EmbeddedInteractive"]'):
        w.decompose()

    blocks: list[str] = []
    images: list[tuple[str, str]] = []  # (filename, caption)
    seen_imgs: set[str] = set()
    img_n = 0

    def add_image(url: str | None, cap: str = "") -> None:
        """Fetch `url` at full resolution and emit its markdown, skipping any
        illustration already pulled in (the index thumbnail and a body figure
        often point at the same master)."""
        nonlocal img_n
        if not url or img_identity(url) in seen_imgs:
            return
        fn = fetch_image(url, slug, img_n + 1)
        if not fn:
            return
        img_n += 1
        seen_imgs.add(img_identity(url))
        images.append((fn, cap))
        blocks.append(f"![{cap}]({fn})")
        if cap:
            blocks.append(f"*{cap}*")

    # Lead illustration. NYT's real full-res art is a <figure aria-label="media">
    # whose <img> srcset carries the superJumbo master — in the header on recent
    # essays, but inside the body on some 2012-2019 ones. The index only knows a
    # master-less section thumbnail, so fall back to it only when no media figure
    # exists. A body media figure used as the lead is skipped in the walk below.
    art = soup.find("article") or soup
    lead_fig = art.select_one('figure[aria-label="media"]')
    if lead_fig is not None:
        add_image(figure_src(lead_fig), clean_caption(lead_fig.find("figcaption")))
    else:
        add_image(idx.get("image_url"))

    # Modern Love essays are single-flow prose: any h2/h3 in the body is a widget
    # label, so we emit only paragraphs and figures.
    for el in body.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name == "p" and el.find_parent("figure") is None:
            txt = inline(el)
            if txt and not is_boilerplate(txt):
                blocks.append(txt)
        elif el.name == "figure":
            if el is lead_fig:                    # already emitted as the lead
                continue
            add_image(figure_src(el), clean_caption(el.find("figcaption")))

    # De-dupe consecutive repeats that the descendants walk can introduce.
    clean: list[str] = []
    for b in blocks:
        if not clean or clean[-1] != b:
            clean.append(b)

    # Strip trailing contributor-bio / kicker paragraphs off the end.
    while clean and not clean[-1].startswith(("!", "#")):
        if is_author_bio(clean[-1], author) or is_boilerplate(clean[-1]):
            clean.pop()
        else:
            break

    return {
        "slug": slug, "title": title, "author": author, "date": date,
        "url": idx.get("url"), "blocks": clean, "n_images": len(images),
        "n_paras": sum(1 for b in clean if not b.startswith(("!", "#", "*"))),
    }


_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _pretty_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{_MONTHS[int(m) - 1]} {int(d)}, {y}"
    except (ValueError, IndexError):
        return iso


def to_markdown(rec: dict) -> str:
    lines = [f"# {rec['title']}", ""]
    meta_bits = []
    if rec["author"]:
        meta_bits.append(f"By {rec['author']}")
    if rec["date"]:
        meta_bits.append(_pretty_date(rec["date"]))
    # Fenced div so the stylesheet can target the byline (renders as
    # <div class="byline"><p>…</p></div>).
    if meta_bits:
        lines += ["::: byline", " · ".join(meta_bits), ":::", ""]
    lines += [b + "\n" for b in rec["blocks"]]
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    common.MD_DIR.mkdir(parents=True, exist_ok=True)
    common.IMG_DIR.mkdir(parents=True, exist_ok=True)
    # Follow the canonical index (articles.json), not the raw HTML dir: the crawl
    # leaves behind alias pages — the same essay at a second URL, sometimes with
    # different copyediting that dedup's exact-text match won't catch — so walking
    # every *.html would re-introduce duplicates. Indexed slugs stay 1:1 with the
    # published index.
    slugs = sys.argv[1:] or sorted(INDEX)
    # Skip Modern Love Podcast episodes crawled as if they were columns (audio,
    # not the written essay). Fall back to the slug when the URL isn't in INDEX.
    kept = [s for s in slugs
            if not common.is_nonessay(INDEX.get(s, {}).get("url") or s, "",
                                      INDEX.get(s, {}).get("title", ""))]
    if len(kept) < len(slugs):
        print(f"skipping {len(slugs) - len(kept)} podcast/non-essay pages")
    slugs = kept

    ok = skipped = 0
    for slug in slugs:
        try:
            rec = extract_one(slug)
        except Exception as e:  # noqa: BLE001
            print(f"ERR  {slug}: {type(e).__name__}: {e}")
            continue
        if not rec or rec["n_paras"] < 3:
            print(f"SKIP {slug}: too little body ({rec['n_paras'] if rec else 0} paras)")
            skipped += 1
            continue
        (common.MD_DIR / f"{slug}.md").write_text(to_markdown(rec), encoding="utf-8")
        ok += 1
        print(f"ok   {slug}: {rec['n_paras']} paras, {rec['n_images']} imgs — "
              f"{rec['author'] or 'no byline'}")
    print(f"\nwrote {ok} markdown files, skipped {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
