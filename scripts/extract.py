"""Turn saved article HTML into clean Markdown + downloaded images.

NYT renders the essay into the DOM under `<section name="articleBody">`, with the
byline and publish date in stable `<meta>` tags. We walk the body in document
order, emitting paragraphs, sub-headings, and figures (with captions), and pull
each referenced image from NYT's open CDN.
"""

from __future__ import annotations

import json
import re
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

def fetch_image(url: str, slug: str, n: int) -> str | None:
    """Download one image; return its local filename (or None on failure)."""
    if not url:
        return None
    url = url.split("?")[0]
    ext = Path(url).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    name = f"{slug}-{n}{ext}"
    dest = common.IMG_DIR / name
    if dest.exists() and dest.stat().st_size > 1000:
        return name
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 1000:
            return None
        dest.write_bytes(data)
        return name
    except Exception:  # noqa: BLE001
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
    img_n = 0

    # Lead image from the index (highest-quality known URL).
    if idx.get("image_url"):
        img_n += 1
        fn = fetch_image(idx["image_url"], slug, img_n)
        if fn:
            images.append((fn, ""))
            blocks.append(f"![]({fn})")

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
            img = el.find("img")
            src = img.get("src") if img else None
            if src:
                img_n += 1
                fn = fetch_image(src, slug, img_n)
                cap = clean_caption(el.find("figcaption"))
                if fn:
                    images.append((fn, cap))
                    blocks.append(f"![{cap}]({fn})")
                    if cap:
                        blocks.append(f"*{cap}*")

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
    slugs = sys.argv[1:] or sorted(p.stem for p in common.HTML_DIR.glob("*.html"))
    # Skip Modern Love Podcast episodes crawled as if they were columns (audio,
    # not the written essay). Fall back to the slug when the URL isn't in INDEX.
    kept = [s for s in slugs
            if not common.is_nonessay(INDEX.get(s, {}).get("url") or s, "")]
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
