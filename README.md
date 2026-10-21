# X Markdown export

Export the public English X Help Center to one Markdown file per article.
Requires Python 3.11+; no API key or authentication is needed.

## Setup and run

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scrape.py --out out/
python scrape.py --limit 30 --out out/
python -m unittest discover -s tests -v
```

Use any installed Python 3.11+ for the first command (this workspace was verified
with `python3.14`). The default is all articles; `--limit` counts successful writes.
Output is UTF-8 and `out/` is gitignored.

To configure the run directly in `scrape.py`, edit the settings near the top:

```python
LIMIT = None  # All articles; change to 30 to export up to 30.
OUT_DIR = "out"  # Relative to your current working directory.
```

Then run `python scrape.py` without arguments. Optional `--limit` and `--out`
arguments override these settings for a single run.

## Design

- Uses the Zendesk articles API, not page scraping. Inspection on 2026-10-20
  returned HTTP 200 without credentials and 415 articles. The locale-free URL
  redirects to `en-us`. The exporter requests `page[size]=100` to enable cursor
  pagination, follows the returned `links.next` URL unchanged, and stops when
  `meta.has_more` is false (including an empty final page). It rejects repeated
  page URLs and missing next links when more results are advertised.
  See [Zendesk's cursor pagination guide](https://developer.zendesk.com/documentation/api-basics/pagination/paginating-through-lists-using-cursor-pagination/)
  and [Articles API reference](https://developer.zendesk.com/api-reference/help_center/help-center-api/articles/#list-articles).
- Requests have a User-Agent, connection/read timeouts, and up to five retries
  with exponential backoff for transient failures. HTTP 429 respects Retry-After.
- BeautifulSoup removes unwanted elements and 1×1 images; markdownify produces
  ATX headings, lists, tables, links, and images. Code blocks are protected and
  fenced with enough backticks to contain literal backticks safely.
- Filenames use normalized Unicode titles plus article IDs. Repeated runs
  overwrite atomically. Renamed articles remove their prior ID-suffixed file.
- Front matter records title, source URL, ID, and update timestamp. Each file has
  a top-level title, and relative URLs remain relative.
- Each article logs its ID, slug, and UTF-8 byte count. Drafts and duplicate IDs
  are skipped. An article failure does not stop later articles. Fetch failures
  stop pagination, retain completed files, and produce a nonzero exit status.
  Summary `fetched` counts encountered records; `failed` also includes fetch
  failures; `written` counts successful exports.

## Limitations

- Exports the public `en-us` collection only, not translations or private content.
- Images remain remote; relative links are not rewritten to local files.
  Original fragment links are retained, but custom HTML anchor IDs may not match
  a Markdown viewer's generated heading anchors.
- Embedded iframes are removed. Complex HTML layout is simplified to Markdown.
  Pixel detection covers explicit 1×1 HTML dimensions and inline CSS dimensions,
  not every possible tracking service.
- Prose trailing spaces and excess blank lines are removed. Code whitespace is
  deliberately preserved, including blank lines and trailing spaces.
- Previously exported articles removed from the server are not deleted.
  The live API is not a transactional snapshot if articles change during a run.

## Verification

The full run exported **415 articles**, with **0 skipped and 0 failed**.
Spot checks covered the Eventbrite article (headings/lists), the RTSP article
(fenced code), and Web Scripting (relative image paths). The conversion fixture
also verifies a relative article link and removal of navigation/footer text.

```sh
ls out | wc -l
grep -L '^# ' out/*.md
grep -l '<div\|<span\|<script' out/*.md
```

The count was 415; both grep commands returned no files.
All 13 unit tests passed. A second full export produced the same 415 filenames
and identical SHA-256 content hashes, confirming clean overwrites without duplicates.
After switching to cursor pagination, a full export to a temporary directory on
2026-10-21 again wrote 415 articles, with 0 skipped and 0 failed. All files had
title headings. Pagination tests cover multiple pages, an empty terminal page,
stopping on `has_more=false` even with a next link, and malformed pagination.
