"""Keep the public index current via the NYT Article Search API — no crawl.

Modern Love headlines and bylines are public API metadata (only the essay *body*
is paywalled), so newly published columns can be discovered without a login or a
headed browser. This script asks the API for recent Modern Love columns and
merges any it hasn't seen into docs/index.json (+ docs/index.csv), the committed
source of truth behind the GitHub Pages table.

It works purely off committed files — it reads and rewrites docs/index.json and
never touches the gitignored crawl in data/ — so it is safe to run in CI (see
.github/workflows/update-index.yml) on a weekly schedule.

The key is read from NYT_API_KEY (a GitHub Actions secret in CI). Use --probe to
print what the API returns while writing nothing; --fq lets you try different
filters from the logs while proving out the Modern Love query.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

import common

DOCS = common.ROOT / "docs"
INDEX_JSON = DOCS / "index.json"
INDEX_CSV = DOCS / "index.csv"

API = "https://api.nytimes.com/svc/search/v2/articlesearch.json"

# The kicker is the cleanest signal separating a Modern Love essay from the rest
# of the Style desk; the post-filters below drop sibling features that share it.
DEFAULT_FQ = 'kicker:"Modern Love"'
SKIP_MATERIAL = {"Interactive Feature", "Audio", "Video", "Slideshow", "Quiz"}
SKIP_DOCTYPE = {"audio", "multimedia"}
SKIP_TITLE_PREFIXES = ("Tiny Love Stories",)


def api_get(params: dict, key: str) -> dict:
    """One Article Search request, with backoff on throttling."""
    url = f"{API}?{urllib.parse.urlencode({**params, 'api-key': key})}"
    req = urllib.request.Request(url, headers={"User-Agent": "modern-love-index/1.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                wait = 20 * (attempt + 1)
                print(f"  {e.code} throttled — sleeping {wait}s")
                time.sleep(wait)
                continue
            body = e.read().decode(errors="replace")[:300]
            raise SystemExit(f"API error {e.code}: {body}")
    raise SystemExit("API: too many retries")


def normalize(d: dict) -> tuple[dict, str | None]:
    """Turn an API doc into an index row, or flag why it isn't a written column."""
    hl = d.get("headline") or {}
    title = (hl.get("main") or "").strip()
    url = d.get("web_url") or ""
    if not url:
        return {"title": title}, "no-url"
    material = d.get("type_of_material") or ""
    doctype = d.get("document_type") or ""
    if material in SKIP_MATERIAL or doctype in SKIP_DOCTYPE:
        return {"title": title}, f"type:{doctype or material}"
    if (d.get("section_name") or "") == "Podcasts":
        return {"title": title}, "section:Podcasts"
    if title.startswith(SKIP_TITLE_PREFIXES):
        return {"title": title}, "tiny-love-stories"
    byl = (d.get("byline") or {}).get("original") or ""
    author = byl[3:].strip() if byl[:3].lower() == "by " else byl.strip()
    if common.is_nonessay(url, author):
        return {"title": title}, "podcast"
    return ({"date": (d.get("pub_date") or "")[:10], "title": title,
             "author": author, "url": url}, None)


def _dump(d: dict, reason: str | None) -> None:
    """One-doc diagnostic line (probe mode) exposing the fields we filter on."""
    hl = d.get("headline") or {}
    byl = (d.get("byline") or {}).get("original") or ""
    path = urllib.parse.urlsplit(d.get("web_url") or "").path
    tag = "keep" if not reason else f"skip:{reason}"
    print(f"    [{tag}] {(d.get('pub_date') or '')[:10]} "
          f"dt={d.get('document_type')!r} tm={d.get('type_of_material')!r} "
          f"sec={d.get('section_name')!r} by={byl!r}")
    print(f"        {path} | {hl.get('main')!r}")


def discover(key: str, fq: str, begin: str, end: str | None, probe: bool) -> list[dict]:
    """Normalized Modern Love rows in [begin, end], paging until the docs run out."""
    kept: dict[str, dict] = {}
    skips: list[str] = []
    page = 0
    while page < 100:
        params = {"fq": fq, "begin_date": begin, "sort": "oldest", "page": page}
        if end:
            params["end_date"] = end
        resp = api_get(params, key).get("response") or {}
        docs = resp.get("docs") or []
        if page == 0:
            hits = (resp.get("meta") or {}).get("hits")
            print(f"  fq={fq!r} {begin}..{end or 'now'} -> hits={hits}, docs/page={len(docs)}")
        if not docs:
            break
        for d in docs:
            row, reason = normalize(d)
            if probe:
                _dump(d, reason)
            if reason:
                skips.append(reason)
            else:
                kept[common.norm_url(row["url"])] = row
        page += 1
        time.sleep(12)  # <= 5 requests/minute
    if probe and skips:
        for reason, n in Counter(skips).most_common():
            print(f"    skipped[{reason}] = {n}")
    return list(kept.values())


def load_index() -> list[dict]:
    if INDEX_JSON.exists():
        return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    return []


def write_index(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r["date"], common.norm_url(r["url"])))
    rows = [{"n": i, "date": r["date"], "title": r["title"],
             "author": r.get("author", ""), "url": r["url"]}
            for i, r in enumerate(rows, 1)]
    DOCS.mkdir(exist_ok=True)
    INDEX_JSON.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    with INDEX_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["n", "date", "title", "author", "url"])
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--probe", action="store_true",
                    help="print what the API returns; write and commit nothing")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="discover columns published on/after this date "
                         "(default: 21 days before the newest indexed column)")
    ap.add_argument("--all", action="store_true",
                    help="scan the whole archive year by year (reconcile mode)")
    ap.add_argument("--fq", default=DEFAULT_FQ,
                    help=f"NYT filter query (default: {DEFAULT_FQ})")
    args = ap.parse_args()

    key = os.environ.get("NYT_API_KEY")
    if not key:
        raise SystemExit("NYT_API_KEY is not set — add it as a GitHub Actions "
                         "secret, or export it locally for a manual run.")

    raw = load_index()
    existing = [r for r in raw if not common.is_nonessay(r["url"], r.get("author", ""))]
    pruned = len(raw) - len(existing)
    have = {common.norm_url(r["url"]) for r in existing}
    newest = max((r["date"] for r in existing), default="2004-01-01")
    print(f"index: {len(existing)} columns, newest {newest}"
          + (f" (pruning {pruned} non-essay rows)" if pruned else ""))

    if args.all:
        found_map: dict[str, dict] = {}
        for year in range(2004, dt.date.today().year + 1):
            for r in discover(key, args.fq, f"{year}0101", f"{year}1231", args.probe):
                found_map[common.norm_url(r["url"])] = r
        found = list(found_map.values())
    else:
        if args.since:
            begin = args.since.replace("-", "")
        else:
            since = dt.date.fromisoformat(newest) - dt.timedelta(days=21)
            begin = since.strftime("%Y%m%d")
        found = discover(key, args.fq, begin, None, args.probe)

    fresh = [r for r in found if common.norm_url(r["url"]) not in have]
    print(f"API returned {len(found)} Modern Love columns, {len(fresh)} new:")
    for r in sorted(fresh, key=lambda r: r["date"]):
        print(f"  + {r['date']}  {r['title'][:56]:58}  {r['author']}")

    if args.probe:
        print("[probe] nothing written.")
        return 0
    if not fresh and not pruned:
        print("already up to date.")
        return 0
    write_index(existing + fresh)
    total = len(existing) + len(fresh)
    note = f"+{len(fresh)}" + (f", -{pruned}" if pruned else "")
    print(f"wrote {INDEX_JSON.relative_to(common.ROOT)} ({note} = {total}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
