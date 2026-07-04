#!/usr/bin/env bash
# Full pipeline: the Modern Love index -> a single EPUB.
#
# Log in ONCE before the first run (interactive, opens a browser):
#   PLAYWRIGHT_BROWSERS_PATH="$PWD/.pw-browsers" .venv/bin/python scripts/login.py
#
# The crawl (step 3) is deliberately slow and polite (~28s between requests, so
# ~8h for the full ~1000 columns). It is resumable — re-run this script and it
# skips whatever is already downloaded. Every step is safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.pw-browsers"
PY=.venv/bin/python

$PY scripts/parse_index.py                            # 1. download + parse the index -> articles.json
$PY scripts/prune_aliases.py                          # 2. drop same-date short-URL aliases (lossless)
$PY scripts/fetch.py --min-delay 16 --max-delay 28    # 3. polite, resumable crawl (visible browser)
$PY scripts/extract.py                                # 4. article HTML -> Markdown + images
$PY scripts/dedup.py                                  # 5. collapse byte-identical duplicate essays
$PY scripts/rename.py                                 # 6. rename files from headlines (+ URL map)
$PY scripts/make_cover.py                             # 7. render the cover (downloads CC0 artwork)
$PY scripts/build_css.py                              # 8. generate the Standard-Ebooks-style stylesheet
$PY scripts/build_epub.py                             # 9. bind data/modern-love.epub

echo "Done -> data/modern-love.epub"
