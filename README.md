# Darkharvest: OOO support knowledge exporter

Darkharvest converts article data from the configured Help Center API into
Markdown. It can also upload those files to an OpenAI vector store for retrieval.
Each article becomes one UTF-8 Markdown file with source metadata, a title,
and the converted article body.

The scraper uses the public Zendesk Help Center API without credentials.
The optional uploader requires an OpenAI API key.

## Requirements and setup

Use Python 3.11 or newer. The uploader requires macOS or Linux because it uses
`fcntl` for file locking.

Run these commands from the repository root:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Replace `python3.11` with another installed Python 3.11+ interpreter if needed.
Dependencies are pinned in `requirements.txt`.

## Export articles to Markdown

To process up to 30 article records:

```sh
python scrape.py --limit 30 --out articles/
```

The examples in this README write exported files to `articles/`, the directory
used by the upload workflow.

To export all articles available from the configured API endpoint, leave `LIMIT`
blank in `.env` (or unset in both `.env` and the environment):

```dotenv
LIMIT=
```

Then run:

```sh
python scrape.py --out articles/
```

`--limit` accepts a positive integer and overrides `LIMIT` for that run.
Set `LIMIT=30` in `.env` to limit exports to 30 API records by default.
There is no CLI flag for an unlimited export; leave `LIMIT` blank or unset.
`--out` overrides `OUT_DIR`. Relative paths resolve from your working directory.
The standalone scraper reads `.env` beside the script; existing environment
variables take precedence. It does not read `ARTICLES_DIR`.

The limit counts encountered API records, including drafts, duplicates, and
records that fail conversion. Therefore, `--limit 30` does not guarantee 30
output files. Export the full collection and check the output count when at
least 30 files are required.

### Output format

Filenames use a normalized title followed by the Zendesk article ID:
`articles/<title-slug>-<id>.md`. Unicode letters are retained; an empty title slug
falls back to `article-<id>.md`.

For example, an article could produce `articles/example-article-123.md` with:

````markdown
---
title: "Example article"
source: "https://support.OOO.com/hc/en-us/articles/123"
id: 123
updated_at: "2026-10-21T00:00:00Z"
---

# Example article

## Instructions

[Related article](/hc/en-us/articles/456)

```python
print("Example")
```
````

This is an illustrative example, not a captured support article.

### Fetching, conversion, and repeat runs

The client requests the endpoint configured by `ARTICLES_URL` in
`src/client.py`, with `page[size]=100`. The endpoint determines the source
collection and locale. It follows cursor pagination through `links.next` until
`meta.has_more` is false. Repeated page URLs and missing next links are treated as errors.
Requests include a User-Agent, 10-second connection and 60-second read timeouts,
and up to five retries with backoff. The retry policy covers HTTP 429 and
selected server errors and respects `Retry-After`.

Only the API's article `body` HTML is converted, avoiding the surrounding page
navigation. BeautifulSoup removes scripts, styles, navigation, headers,
footers, iframes, noscript elements, empty elements, and explicitly sized 1×1
images. Markdownify converts the remaining content into headings, lists,
tables, links, and images.

Relative link and image targets remain relative. Images are referenced without
being downloaded. Preformatted code becomes fenced blocks, preserving code
whitespace and using longer fences when the code contains backticks. Prose
trailing whitespace is stripped, repeated blank lines are collapsed, and each
file ends with one newline.

On repeat runs, the exporter compares the complete Markdown bytes using
SHA-256, including front matter. New or changed files are replaced atomically;
unchanged files retain their timestamps. A renamed article gets a new filename,
and its previous ID-suffixed file is removed. A metadata-only change also counts
as an update. Articles removed from the server are not deleted locally.

Drafts and duplicate IDs are skipped. An individual conversion or write failure
is logged, and processing continues. A fetch failure stops pagination while
retaining completed files. Any recorded failure produces a nonzero exit status.

### Export logs

Every scraper run writes to both the terminal and `logs/scraper.log` (UTF-8).
The log directory is created automatically. File logs include timestamps and
levels, and append to previous runs instead of overwriting them. Each run starts
with `Run started: limit=... out=...` and ends with a summary; errors include
tracebacks. Logs are flushed as records are written, so progress is available
while the scraper runs. This also applies when invoked through `main.py`.
Change `LOG_PATH` in `scrape.py` to choose another location; relative paths resolve
from your working directory. The default `logs/` directory is gitignored.

Each successful article logs its ID, slug, UTF-8 byte count, and status:
`new`, `updated`, or `unchanged`. The final summary includes:

| Field | Meaning |
| --- | --- |
| `fetched` | API records encountered in this run, capped by the limit. |
| `skipped` | Draft or duplicate records skipped. |
| `failed` | Article failures plus any fetch failure. |
| `written` | Files created or updated; equals `new + updated`. |
| `new`, `updated`, `unchanged` | Successful exports grouped by their local file status. |

For example, an unchanged 30-article rerun could report:

```text
Summary: fetched=30 skipped=0 failed=0 written=0 new=0 updated=0 unchanged=30
```

## Upload to an OpenAI vector store

### Configuration

If you do not already have a `.env` file, copy the example:

```sh
cp .env.example .env
```

If `.env` already exists, merge the example settings into it. Set
`OPENAI_API_KEY` to your key. The remaining settings are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARTICLES_DIR` | `articles` | Directory containing the Markdown files to upload. |
| `INGESTION_LOG_PATH` | `logs/ingestion.log` | File receiving uploader logs. |
| `OPENAI_VECTOR_STORE_ID` | Required | Existing vector store ID; read from `.env` or the environment. |

Existing environment variables take precedence over `.env`. Relative paths
resolve from your working directory. Both entrypoints load `.env` beside the
script. `.env`, `out/`, `articles/`, and `logs/` are gitignored.

### Run both steps

```sh
python main.py --limit 30
```

`main.py` loads `.env` beside the script, exports into `ARTICLES_DIR`, then runs
the uploader only if the export succeeds. It returns a nonzero exit status if
either step fails. Without `--limit`, it uses `LIMIT` from the environment or `.env`.

**The limit applies only to scraping.** Uploading processes every top-level
`*.md` file in `ARTICLES_DIR`, including files from previous exports. It does
not search subdirectories.

To run the steps separately with the default upload directory:

```sh
python scrape.py --limit 30 --out articles/
python upload_knowledge.py
```

If you change `ARTICLES_DIR`, pass the same directory to the scraper's `--out`.
The uploader is configured through environment variables and `.env`, not CLI
options.

### Store reuse and synchronization

Set the existing store ID in `.env`:

```dotenv
OPENAI_VECTOR_STORE_ID=vs_your_existing_store
```

The uploader validates that store before synchronizing. Missing or inaccessible
IDs fail the run; it never creates a store or reads/writes an ingestion state
file. Existing environment variables override `.env`, including on ECS.

Each article is uploaded as one file with its original bytes, including front
matter and code whitespace. The uploader identifies articles by the numeric
ID suffix in the filename, falling back to the whole filename if no suffix is
present. Duplicate local identities are rejected before uploads start.

Managed remote files carry an ownership marker, article identity, and content
hash. The uploader reads attachment metadata in pages of 100 (without downloading
remote file contents), checks all pages, and skips completed
files with matching hashes. Changed files are indexed successfully before old
managed versions are detached. Reruns also retry unfinished replacement cleanup.
Unmanaged files, including older uploads without ownership metadata, are left
untouched.

Article failures are logged individually while remaining articles continue.
The uploader requests five SDK retries, a 60-second request timeout, and a
300-second indexing polling limit per article. A local lock prevents overlapping
runs using the same article directory via `articles/.upload.lock`; it does not
coordinate different machines or separate directories targeting the same store.

### Chunking and ingestion logs

New attachments request static chunking with **800 tokens per chunk and 400
tokens of overlap**. Each article remains a single uploaded file; the script
does not create separate Markdown chunks. Unchanged completed attachments are
reused with their existing chunking policy.

The uploader writes logs to the console and `INGESTION_LOG_PATH`. Its summary
reports:

| Field | Meaning |
| --- | --- |
| `articles` | Local Markdown files selected for this run. |
| `uploaded` | Files newly indexed with replacement cleanup completed. |
| `skipped` | Matching completed files reused, with cleanup completed. |
| `failed` | Articles whose upload, indexing, or cleanup failed. |
| `embedded_files` | Files successfully indexed during this run. |
| `embedded_chunks_estimated` | Local chunk estimate for those newly indexed files. |
| `vector_store_id` | Store used for the run. |

Chunk estimates use tiktoken's `cl100k_base` encoding of the original Markdown.
For a nonempty file with `T` tokens, the estimate is
`1 + ceil(max(0, T - 800) / 400)`. This is a local estimate, not an API-reported
embedding count; server-side processing can differ. The tokenizer may download
encoding data on first use.

These counters describe this run, not the whole store. An unchanged rerun has
zero newly embedded files and estimated chunks. If indexing succeeds but old
attachment cleanup fails, the new file still contributes to the embedding
counters, and the article also counts as failed.

## Project layout

```text
.
├── AGENTS.md                 # Repository working instructions
├── README.md                 # Setup, usage, and design documentation
├── requirements.txt          # Pinned Python dependencies
├── .env.example              # Scraper and uploader configuration template
├── .gitignore                # Local and generated file exclusions
├── main.py                   # Run export, then upload
├── scrape.py                 # Export CLI and local change detection
├── upload_knowledge.py       # Vector store synchronization
├── src/
│   ├── __init__.py
│   ├── client.py             # API requests, retries, and cursor pagination
│   ├── convert.py            # HTML cleaning and Markdown conversion
│   └── slug.py               # Unicode filenames with article IDs
└── tests/
    ├── test_export.py        # Conversion, slugs, API client, and export tests
    ├── test_main.py          # Pipeline sequencing and failure handling
    ├── test_upload.py        # Upload synchronization and chunk estimates
    └── fixtures/
        ├── article.html      # Conversion input
        └── article.md        # Expected Markdown output
```

Local configuration and runtime output are separate from the source files:

```text
.
├── .env                      # Local configuration and API key
├── articles/                 # Markdown output used by the documented workflow
└── logs/
    ├── ingestion.log         # Upload progress and errors
    ├── scraper.log           # Scraper progress and errors, appended across runs
    └── last-run.json         # Latest pipeline summary
```

Runtime paths can be changed through the settings described above. The existing
`out/` directory is an alternate export location; the commands in this README
use `articles/` consistently.

## Verification

Run the existing tests:

```sh
python -m unittest discover -s tests -v
```

The suite covers conversion fixtures, code whitespace, relative links, element
removal, slugs, pagination, local change detection, pipeline ordering, and
upload synchronization. API and SDK operations are mocked; passing tests do not
verify live credentials, remote indexing, or current article availability.

After an export, check the generated files:

```sh
find articles -maxdepth 1 -type f -name '*.md' | wc -l
grep -L '^# ' articles/*.md
grep -l '<div\|<span\|<script' articles/*.md
```

For the export task, the count should be at least 30. The first grep lists
files missing a title heading; the second flags possible leftover HTML for inspection. Literal
HTML inside a preserved code example may also match. No matches produce grep
exit status 1.

Spot-check at least three files for readable headings, fenced code, unchanged
relative targets, and absence of navigation/footer text. Existing files count
toward the directory total, so use a fresh output directory when measuring a
single run. Article counts depend on the live collection and selected limit.

## Known limitations

- Export coverage follows the configured API endpoint; the client does not
  discover additional collections or locales automatically. There is no
  page-scraping fallback if the API is unavailable, and a changing collection
  is not a transactional snapshot.
- Complex HTML layouts are simplified and embedded iframes are removed. Custom
  HTML anchors may not match a Markdown viewer's generated heading anchors.
- Images remain remote or relative, and article links are not rewritten to
  local Markdown files. Pixel removal detects explicit 1×1 dimensions, not
  every tracking mechanism.
- Code whitespace is preserved, including trailing spaces and repeated blank
  lines. Prose whitespace normalization does not apply inside fenced blocks.
- Removed source articles remain on disk, and locally removed articles are not
  pruned from the vector store.
- Replacement detaches obsolete managed files from the selected store; it does
  not delete their underlying account files. Old stores and unmanaged uploads
  require separate cleanup.
- Interrupted file creation or ambiguous network responses can leave unattached
  account files. Local locks and hashes do not make remote operations atomic.

## Daily AWS job: ECS Fargate + EventBridge Scheduler

Local and container runs use the same pipeline: scrape Markdown, list all
vector-store attachments, and compare SHA-256 against their OpenAI metadata
(`manager`, `article_key`, `sha256`). Hashes include front matter. A fresh
container can reuse unchanged files without a local article cache or manifest.
Always configure the same `OPENAI_VECTOR_STORE_ID`.

`main.py` writes `logs/last-run.json` (override `RUN_ARTIFACT_PATH`) and prints
the same JSON to stdout, with status, timestamps and upload counts. CloudWatch
retains stdout after the task exits; the local report disappears with the
container. No S3 bucket or AWS credentials are needed by the application.

### Manual AWS setup

Build and push the Docker image to ECR, then configure these resources in the
AWS Console:

1. Store the OpenAI API key as a plaintext secret in Secrets Manager.
2. Create an ECS cluster and a Fargate task definition using the ECR image.
   Set `OPENAI_VECTOR_STORE_ID` and blank `LIMIT`; inject `OPENAI_API_KEY` from
   Secrets Manager. Configure the `awslogs` log driver.
3. Give the execution role ECR/log permissions and access to the secret.
4. Create an EventBridge Scheduler schedule targeting ECS RunTask, with
   `cron(0 2 * * ? *)` and timezone UTC (**09:00 Vietnam time**). Select a public
   subnet with an internet route, enable a public IP, and allow outbound HTTPS.
   Give the Scheduler role RunTask and PassRole permissions for this task.

The task runs once and exits. Run it manually first and check the container exit
code and CloudWatch summary before relying on the schedule. There is no
deployment automation in this repository. Avoid overlapping manual/scheduled
runs against the same store; the local lock cannot coordinate containers.
Scheduler retries delivery errors, not application failures.

### Two-run verification

Set `OPENAI_API_KEY` and `OPENAI_VECTOR_STORE_ID` in `.env`, then run twice:

```sh
LIMIT= python main.py
LIMIT= python main.py
```

For a store without managed files and an unchanged collection of N articles,
expect first run `added=N updated=0 skipped=0 failed=0`, then
`added=0 updated=0 skipped=N failed=0`. N is measured, not hardcoded to 415.
Tests simulate these operations with mocked OpenAI; they are not evidence of
live indexing or AWS deployment.

To run the same pipeline in a container:

```sh
docker build --platform linux/amd64 -t darkharvest .
docker run --rm --env-file .env -e LIMIT= darkharvest
```

The image includes `src/`, runs as an unprivileged user, and excludes local
secrets and exports. For a small smoke run, append `python main.py --limit 30`
to the Docker run command. Submit the CloudWatch log-group URL and latest run
summary after a successful live run.
