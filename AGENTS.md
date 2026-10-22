# AGENTS.md

You are acting as a senior engineer. Optimize for: correct, readable, verifiable, small. No gold-plating.

## Task

Scrape ≥ 30 articles from `support.optisigns.com` and convert each to clean Markdown.

Requirements:
- Pull **≥ 30** articles (aim for all available; hard minimum 30).
- One file per article: `<ARTICLES_DIR>/<slug>.md`. Configure `ARTICLES_DIR` in `.env` (default: `articles`).
- Preserve: **headings, code blocks, relative links**.
- Remove: nav, header/footer, ads, scripts, styles, tracking junk.
- Hint from interviewer: use the Zendesk Help Center API (articles endpoint).

## Working rules

1. **Verify, don't assume.** Before writing the pipeline, hit the API once and inspect the real JSON (keys, pagination, locale, `body` HTML shape). Do not hardcode assumptions about fields.
2. **Prefer the API over HTML scraping.** The `body` field is article-only HTML, so nav/ads never enter. Fall back to page scraping only if the API is blocked.
3. **Plan first.** Post a 5-line plan, then implement. Ask at most one question, only if blocked.
4. **Small steps.** Fetch → inspect → convert one article → eyeball output → scale to all → add tests.
5. **Report with evidence.** Finish with counts and sample output, not claims.

## Suggested approach

- Endpoint (verify first): `https://support.optisigns.com/api/v2/help_center/{locale}/articles.json?per_page=100`
  - Paginate by following `next_page` until `null`.
  - Check whether the locale segment is needed or the plain `/articles.json` works.
  - Skip `draft: true` articles.
- Fields to use: `id`, `title`, `body`, `html_url`, `updated_at`.
- Conversion: `BeautifulSoup` (clean) → `markdownify` (convert). Heading style `ATX` (`#`).
- Slug: slugified title; append `-<id>` on collision (or always) for uniqueness and stability.
- File format: optional YAML front matter (`title`, `source`, `id`, `updated_at`), then `# Title`, then body.

## Cleaning rules (pre-convert, on the HTML)

- Remove: `script`, `style`, `nav`, `header`, `footer`, `iframe`, `noscript`, tracking pixels (1x1 images), empty tags.
- Keep `<pre>` / `<code>` intact → fenced code blocks. Do not let the converter collapse whitespace inside code.
- **Links: leave relative hrefs relative** (e.g. `/hc/en-us/articles/...`). Do not absolutize. Optional flag to rewrite internal article links to local `<slug>.md`.
- Images: keep `![alt](src)` as-is; do not download unless time allows.
- Collapse 3+ blank lines to 2. Strip trailing whitespace. End file with a single newline.

## Engineering requirements

- Python 3.11+, `requests`, `beautifulsoup4`, `markdownify`. Pin versions in `requirements.txt`.
- Layout:
  ```
  .
  ├── AGENTS.md
  ├── README.md
  ├── requirements.txt
  ├── scrape.py          # CLI entrypoint
  ├── src/
  │   ├── client.py      # API fetch + pagination + retries
  │   ├── convert.py     # HTML -> clean Markdown
  │   └── slug.py
  ├── tests/
  └── articles/          # Default ARTICLES_DIR; generated, gitignored
  ```
- Pipeline CLI: `python main.py --limit N` reads `ARTICLES_DIR` from `.env` and passes it to the scraper. Omit `--limit` and leave `LIMIT` blank for all articles.
- Export only: run from the repository root and pass the configured directory explicitly (standalone `scrape.py` does not read `ARTICLES_DIR` itself):
  ```sh
  ARTICLES_DIR="$(python -c 'import os; from dotenv import load_dotenv; load_dotenv(".env"); print(os.getenv("ARTICLES_DIR", "articles"))')"
  python scrape.py --limit 30 --out "$ARTICLES_DIR"
  ```
- Relative `ARTICLES_DIR` paths resolve against the current working directory. Keep custom generated directories gitignored.
- Network: set a `User-Agent`, timeouts, retry with backoff, honor `429` + `Retry-After`.
- Idempotent: re-running overwrites cleanly, no duplicates.
- Logging: one line per article (id, slug, bytes). Summary at end: fetched / skipped / failed.
- Failure isolation: one bad article must not abort the run.
- No secrets, no auth needed (public Help Center API). Verify this; don't assume.

## Tests (keep light)

- `convert`: fixture HTML → expected Markdown for heading, code block, relative link, nav removal.
- `slug`: collisions, unicode, empty title.
- Client: pagination with a mocked two-page response.

## Definition of done

Use the shell variable `ARTICLES_DIR` loaded by the export-only command above.

- [ ] `find "$ARTICLES_DIR" -maxdepth 1 -type f -name '*.md' | wc -l` ≥ 30
- [ ] Spot-check 3 files: headings intact, code fenced, relative links untouched, no nav/footer text
- [ ] `grep -L '^# ' "$ARTICLES_DIR"/*.md` returns nothing (every file has a title)
- [ ] `grep -l '<div\|<span\|<script' "$ARTICLES_DIR"/*.md` returns nothing (no leftover HTML)
- [ ] Tests pass
- [ ] README: setup, run command, design decisions, known limitations
