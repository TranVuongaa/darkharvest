# Darkharvest

Export OptiSigns support articles as clean Markdown and synchronize them with an
existing OpenAI vector store for a support assistant.

**Setup** — Python 3.11+ on macOS or Linux. From the repository root:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env  # Only if you do not already have a .env file.
```

For uploads, set `OPENAI_API_KEY` and `OPENAI_VECTOR_STORE_ID` in `.env`.
Set `ARTICLES_DIR` in `.env` to the directory used for exports and uploads
(default: `articles`):

```dotenv
ARTICLES_DIR="articles"
LIMIT=
```

Leave `LIMIT` blank to process all articles. Run commands from the repository
root; relative paths resolve against the current working directory. Add any
custom generated directory inside the repository to `.gitignore`.

**Run locally**

```sh
LIMIT= python main.py                       # Export all articles, then upload.
python -m unittest discover -s tests -v     # Run tests.
```

`--limit` counts API records, so skipped or failed records can reduce the output
count. Uploads process all Markdown files in `ARTICLES_DIR`.

## Delta synchronization

Each run exports articles again, then calculates SHA-256 over the exact bytes of
each Markdown file (including front matter and whitespace). The uploader lists
all vector-store file attachments, following SDK pagination, and compares this
local digest with remote `attributes.sha256`; it does not download remote content
or use a local hash cache. SHA-256 is the comparison value; `attributes` is where
that value and the article identity are stored:

```json
{
  "manager": "optibot-articles-v1",
  "article_key": "123456789",
  "sha256": "<SHA-256 hex digest of the Markdown bytes>"
}
```

`article_key` is the Zendesk ID at the end of the filename, falling back to the
filename when no ID is present. Only attachments with this `manager` are managed.

| Remote state for the article key | Result |
| --- | --- |
| No managed attachment | Upload and index; count as `added`. |
| A `completed` attachment has the same SHA-256 | Skip upload/indexing; count as `skipped`. |
| Managed attachments exist, but none is completed with the same SHA-256 | Upload and index a replacement; count as `updated`. |



**Sample assistant answer** — “How do I add a YouTube video?”

<a href="images/assistant_answer.png"><img src="images/assistant_answer.png" alt="OptiBot answering how to add a YouTube video in OptiSigns, with a source citation" height="280"></a>
