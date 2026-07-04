"""Audit the column list for suspicious gaps.

Modern Love is a weekly column, so any stretch longer than three weeks between
consecutive dates points to columns missing from the source index rather than a
real hiatus. Reads the pristine index (articles_raw.json if present, else
articles.json) and prints every gap plus an estimate of how many columns fall in
it.
"""

from __future__ import annotations

import datetime as dt
import json

import common

GAP_DAYS = 21


def main() -> int:
    src = common.DATA / "articles_raw.json"
    if not src.exists():
        src = common.DATA / "articles.json"
    dates = sorted({a["date"] for a in json.loads(src.read_text())})
    days = [dt.date.fromisoformat(d) for d in dates]

    gaps, missing = [], 0
    for a, b in zip(days, days[1:]):
        delta = (b - a).days
        if delta > GAP_DAYS:
            n = delta // 7 - 1
            missing += n
            gaps.append((a.isoformat(), b.isoformat(), delta, n))

    print(f"{len(dates)} column dates, {dates[0]} … {dates[-1]}")
    print(f"{len(gaps)} gaps >{GAP_DAYS} days, ~{missing} columns likely missing\n")
    for a, b, delta, n in gaps:
        print(f"  {a} -> {b}   {delta:4}d   ~{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
