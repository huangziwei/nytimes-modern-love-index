# Modern Love → EPUB

So I subcribed to NYTimes (again) for a year, just for some old book reviews in the TimesMachine from the 60s. And then I think, hey, why don't I read a bit more, such as that famous Modern Love column? But reading articles on the computer screen hurts my eyes and it'd be great to just read them on e-ink devices. Thus we have this repo.

The scripts here are for setting up the crawler environement, crawling the Modern Love columns as html, emsembling them into an EPUB.

You need your own active NYTimes subscription to run the code.

## Requirements

- `uv`
- `pandoc`
- A **desktop with a display** (macOS or Linux). Login and crawling drive a *visible* Chromium window; NYT's bot protection (DataDome + Cloudflare)
rejects headless clients, so this can't run on a headless server.

## Usage

```bash

# venv + deps + Chromium
./setup.sh 

# log in to NYT once (opens a browser window):
PLAYWRIGHT_BROWSERS_PATH="$PWD/.pw-browsers" .venv/bin/python scripts/login.py

# index → crawl → EPUB  
./run.sh                                       
```

The final output is `data/modern-love.epub`. The crawl is resumable — if it stops, just re-run `./run.sh`; finished columns are skipped.  If your login expires mid-crawl the fetcher stops itself rather than saving empty pages; re-run `login.py` and continue.

It'll take about ~8h to finish because I set the interval to be ~30s per essay. 

## Credits

- Index: [Ben Koski](https://ben.koski.us/nyt/modern-love)
- Cover art: Émile Friant, *Cast Shadows* (1891) — public domain (CC0), via
  [Standard Ebooks](https://standardebooks.org/artworks)
- Titling: [League Spartan](https://github.com/theleagueof/league-spartan) (SIL OFL)
- Typography adapted from Standard Ebooks' `core.css`

## License

The **code** in this repository is released under the MIT License (see [`LICENSE`](LICENSE)). It does **not** include, and is not a license to, any NYT content; that is downloaded by you, for you, under your own subscription.
