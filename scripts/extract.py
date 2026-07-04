"""Turn saved article HTML into clean Markdown + downloaded images.

NYT renders the essay into the DOM under `<section name="articleBody">`, with the
byline and publish date in stable `<meta>` tags. We walk the body in document
order, emitting paragraphs, sub-headings, and figures (with captions), and pull
each referenced image from NYT's open CDN.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

import common

UA = {"User-Agent": common.UA}
INDEX = {a["slug"]: a for a in json.loads((common.DATA / "articles.json").read_text())}

# NYT's own promo/submission furniture that lives inside the article body but
# isn't part of the essay. Matched case-insensitively against a paragraph.
import re as _re  # noqa: E402

_PROMO = _re.compile(
    r"sign up for love letter"
    r"|our weekly email about modern love"
    r"|^want more from modern love"
    r"|^want more\?"
    r"|to find previous modern love"
    r"|to submit a modern love essay"
    r"|modern love can be reached"
    r"|tiny love stories"            # separate NYT product cross-promo, not essay
    r"|/newsletters/love-letter"     # inline newsletter sign-up link
    r"|for the podcast, essays and more, visit",
    _re.I,
)


def is_boilerplate(text: str) -> bool:
    return bool(_PROMO.search(text))


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
            if c.name in ("em", "i"):
                parts.append(f"*{inline(c)}*")
            elif c.name in ("strong", "b"):
                parts.append(f"**{inline(c)}**")
            elif c.name == "a":
                txt = inline(c)
                href = c.get("href", "")
                parts.append(f"[{txt}]({href})" if href else txt)
            elif c.name == "br":
                parts.append("\n")
            else:
                parts.append(inline(c))
    return "".join(parts).strip()


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
    published = meta(soup, property="article:published_time")
    date = (published or idx.get("date") or "")[:10]

    body = soup.find("section", attrs={"name": "articleBody"}) or soup.find("article")
    if body is None:
        return None

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

    for el in body.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name == "p" and el.find_parent("figure") is None:
            txt = inline(el)
            if txt and not is_boilerplate(txt):
                blocks.append(txt)
        elif el.name in ("h2", "h3"):
            txt = inline(el)
            if txt:
                blocks.append(f"## {txt}")
        elif el.name == "figure":
            img = el.find("img")
            src = img.get("src") if img else None
            if src:
                img_n += 1
                fn = fetch_image(src, slug, img_n)
                cap_el = el.find("figcaption")
                cap = inline(cap_el) if cap_el else ""
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

    return {
        "slug": slug, "title": title, "author": author, "date": date,
        "url": idx.get("url"), "blocks": clean, "n_images": len(images),
        "n_paras": sum(1 for b in clean if not b.startswith(("!", "#", "*"))),
    }


def to_markdown(rec: dict) -> str:
    lines = [f"# {rec['title']}", ""]
    meta_bits = []
    if rec["author"]:
        meta_bits.append(f"By {rec['author']}")
    if rec["date"]:
        meta_bits.append(rec["date"])
    if meta_bits:
        lines += [f"*{' · '.join(meta_bits)}*", ""]
    lines += [b + "\n" for b in rec["blocks"]]
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    common.MD_DIR.mkdir(parents=True, exist_ok=True)
    common.IMG_DIR.mkdir(parents=True, exist_ok=True)
    slugs = sys.argv[1:] or sorted(p.stem for p in common.HTML_DIR.glob("*.html"))

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
