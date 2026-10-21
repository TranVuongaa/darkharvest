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
with `python3.14`). The default is all articles; `--limit` caps the number of API
articles processed.
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
- Filenames use normalized Unicode titles plus article IDs. New and changed
  files are written atomically; unchanged files are not rewritten. Renamed
  articles remove their prior ID-suffixed file.
- Front matter records title, source URL, ID, and update timestamp. Each file has
  a top-level title, and relative URLs remain relative.
- Each article logs its ID, slug, and UTF-8 byte count. Drafts and duplicate IDs
  are skipped. An article failure does not stop later articles. Fetch failures
  stop pagination, retain completed files, and produce a nonzero exit status.
  Summary `fetched` counts encountered records and never exceeds `--limit`;
  `failed` also includes fetch
  failures; `written` counts files actually created or updated.
- Each successful export also reports `status=new`, `updated`, or `unchanged`.
  The exporter matches existing files by article ID (including renamed titles)
  and compares SHA-256 hashes of the complete UTF-8 Markdown, including front
  matter. Missing files are `new`; different hashes are `updated`; matching
  hashes are `unchanged`. A timestamp-only metadata change counts as an update,
  and content changes are detected even when `updated_at` stays the same.
  The summary includes all three status counts. `new + updated` equals
  `written`; unchanged files retain their existing contents and timestamps.
  Counts cover only articles processed in this run and use the selected output
  directory as the baseline; an empty directory makes every export `new`.

  Example repeat run:
  `Summary: fetched=5 skipped=0 failed=0 written=0 new=0 updated=0 unchanged=5`

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

## Upload articles to OpenAI

Run both steps in sequence with:

```sh
python main.py
python main.py --limit 30
```

`main.py` loads `.env` beside the script and uses `ARTICLES_DIR` (default:
`articles`) for both export and upload. Relative paths remain relative to your
current working directory. Without `--limit`, it uses the current `LIMIT` in
`scrape.py`. Upload starts only if scraping succeeds; failures from either step
produce a nonzero exit status. Upload processes all Markdown files in
`ARTICLES_DIR`, including files from previous exports.

Install `requirements.txt` again to include the pinned OpenAI SDK and dotenv
packages. The uploader requires an OpenAI API key, unlike the public scraper.
Set `OPENAI_API_KEY` in your environment or a local `.env` file, then run:

```sh
python -m pip install -r requirements.txt
python scrape.py --out articles/
python upload_knowledge.py
```

Copy `.env.example` to `.env` if you do not already have one; otherwise merge
its settings into your existing `.env`. Set your API key and configure:

```dotenv
ARTICLES_DIR="articles"
INGESTION_LOG_PATH="logs/ingestion.log"
INGESTION_STATE_PATH=".ingestion-state.json"
OPENAI_VECTOR_STORE_ID=""
```

Settings are loaded as strings. Existing environment values take precedence
over `.env` values.

Paths are relative to your current working directory. `ARTICLES_DIR` contains
the Markdown articles to upload; `INGESTION_LOG_PATH` is the uploader log file,
and `INGESTION_STATE_PATH` stores the vector store ID between runs.
The generated `articles/` directory is gitignored.

The first run creates a vector store and saves its ID in
`.ingestion-state.json` before uploading. Keep this file: subsequent runs reuse
that store. The ID is also printed and recorded in `logs/ingestion.log`.
To select an existing store on the first run, set `OPENAI_VECTOR_STORE_ID` in `.env`
or your environment.
When this setting is blank or unset, saved state is used.
A store conflicting with saved state is rejected; use a separate `INGESTION_STATE_PATH`
when intentionally targeting another store.

Each Markdown article is uploaded as **one file**, byte for byte, preserving
front matter (including `source`), relative links and code whitespace. OpenAI
handles retrieval chunking internally. There are no separate `_1.md`, `_2.md`
chunk uploads. Remote attributes record the stable article ID from the filename,
the SHA-256 content hash, and the uploader's ownership marker. SDK pagination
checks all existing attachments. Unchanged completed files are skipped; changed
articles are indexed successfully before old managed versions are detached.
Filenames without an ID suffix use the whole filename as their identity.
Duplicate local IDs are rejected instead of uploading conflicting copies.

Failures are logged per article and produce a nonzero exit status while other
articles continue. Reruns retry failed articles and unfinished replacement
cleanup. The SDK retries transient requests, and indexing polling has a
five-minute limit per article. A local file lock prevents overlapping runs
using the same state path (macOS/Linux). Do not run multiple machines or
separate state files against the same store concurrently.

Older uploads from the previous chunk-based script have no ownership metadata
and are left untouched, even when selecting their existing store. For a clean
migration, use a new store and configure your application with its printed ID.
Old stores and chunk uploads are not automatically deleted. Replacement only
detaches old files from this store; it does not delete the underlying account
files, which could be used elsewhere. Articles removed locally are not pruned.
A process kill or ambiguous network response during file creation may leave an
unattached account file; local locking and hash checks do not make remote
operations transactional. Losing the state file without supplying the store ID
will create another store.

Uploader verification is offline with a mocked SDK: byte preservation, repeated
runs, renamed and changed articles, failure isolation, interrupted replacement,
legacy-file preservation, duplicate input IDs, and saved store reuse.
