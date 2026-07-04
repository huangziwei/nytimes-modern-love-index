#!/usr/bin/env bash
# One-time environment setup: a project-local virtualenv, Python dependencies,
# and the Chromium build Playwright drives (kept inside the repo so nothing
# touches your system Chrome or your home directory).
#
# Prerequisites you must install yourself:
#   - uv      https://docs.astral.sh/uv/        (Python + venv manager)
#   - pandoc  https://pandoc.org/installing.html (Markdown -> EPUB)
# A desktop with a display is required: login and crawling drive a *visible*
# Chromium window (NYT's bot protection rejects headless clients).

set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null 2>&1 || { echo "error: install uv first — https://docs.astral.sh/uv/"; exit 1; }
command -v pandoc >/dev/null 2>&1 || echo "warning: pandoc not found — required by scripts/build_epub.py"

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.pw-browsers" .venv/bin/python -m playwright install chromium

cat <<'EOF'

Setup complete. Next:
  1. Log in to your NYT account once (opens a browser window):
       PLAYWRIGHT_BROWSERS_PATH="$PWD/.pw-browsers" .venv/bin/python scripts/login.py
  2. Run the pipeline (the crawl is slow and resumable — see README):
       ./run.sh
EOF
