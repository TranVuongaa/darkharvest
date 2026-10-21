#!/usr/bin/env python3
"""Upload whole articles and synchronize managed files in an OpenAI vector store."""

import fcntl
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
import tiktoken

LOG = logging.getLogger("optibot.ingestion")
MANAGER = "optibot-articles-v1"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 400
CHUNKING_STRATEGY = {
    "type": "static",
    "static": {"max_chunk_size_tokens": CHUNK_SIZE,
               "chunk_overlap_tokens": CHUNK_OVERLAP},
}


def estimate_chunks(text: str) -> int:
    """Estimate sliding windows; OpenAI's parsed/tokenized text can differ."""
    tokens = len(tiktoken.get_encoding("cl100k_base").encode_ordinary(text))
    if not tokens:
        return 0
    remaining = max(0, tokens - CHUNK_SIZE)
    stride = CHUNK_SIZE - CHUNK_OVERLAP
    return 1 + (remaining + stride - 1) // stride


def article_key(path: Path) -> str:
    """Exporter filenames end in the stable Zendesk ID, even after a rename."""
    match = re.search(r"-(\d+)$", path.stem)
    return match.group(1) if match else path.name


def synchronize(client, store_id: str, articles: list[Path]) -> dict[str, int]:
    counts = dict(added=0, updated=0, uploaded=0, skipped=0, failed=0,
                  embedded_files=0, embedded_chunks_estimated=0)
    existing = defaultdict(list)
    # Fetch metadata only, 100 per page; SDK iteration follows every page.
    for file in client.vector_stores.files.list(vector_store_id=store_id, limit=100):
        attrs = file.attributes or {}
        if attrs.get("manager") == MANAGER:
            existing[attrs.get("article_key")].append(file)

    keys = [article_key(path) for path in articles]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate article IDs in input; remove stale local copies first")

    for path, key in zip(articles, keys):
        try:
            content = path.read_bytes()
            if not content.decode("utf-8").strip():
                raise ValueError("Empty article")
            digest = hashlib.sha256(content).hexdigest()
            previous = existing[key]
            current = next(
                (file for file in previous
                 if file.status == "completed"
                 and (file.attributes or {}).get("sha256") == digest),
                None,
            )
            action = "skipped"
            if current is None:
                chunks = estimate_chunks(content.decode("utf-8"))
                # Keep the original bytes: front matter, relative URLs and code.
                uploaded = client.files.create(
                    file=(path.name, content, "text/markdown"), purpose="assistants",
                )
                try:
                    current = client.vector_stores.files.create_and_poll(
                        vector_store_id=store_id,
                        file_id=uploaded.id,
                        attributes={"manager": MANAGER, "article_key": key,
                                    "sha256": digest},
                        max_wait_seconds=300,
                        chunking_strategy=CHUNKING_STRATEGY,
                    )
                    if current.status != "completed":
                        raise RuntimeError(
                            f"Indexing status={current.status}: {current.last_error}"
                        )
                except Exception:
                    try:
                        client.files.delete(uploaded.id)
                    except Exception:
                        LOG.exception("Could not clean failed upload %s", uploaded.id)
                    raise
                action = "uploaded"
                # Indexing succeeded even if obsolete-file cleanup later fails.
                counts["embedded_files"] += 1
                counts["embedded_chunks_estimated"] += chunks
                LOG.info("id=%s file=%s embedded_files=1 embedded_chunks_estimated=%d",
                         key, path.name, chunks)

            # Retry also cleans an interrupted replacement: matching hashes skip
            # upload, but obsolete managed attachments are still removed.
            for old in previous:
                if old.id != current.id:
                    client.vector_stores.files.delete(old.id, vector_store_id=store_id)
            counts[action] += 1
            if action == "uploaded":
                counts["updated" if previous else "added"] += 1
            LOG.info("id=%s file=%s bytes=%d status=%s", key, path.name, len(content), action)
        except Exception:
            counts["failed"] += 1
            LOG.exception("id=%s file=%s status=failed", key, path.name)
    return counts


def resolve_store(client, requested: str | None) -> str:
    store_id = (requested or "").strip()
    if not store_id:
        raise ValueError("Set OPENAI_VECTOR_STORE_ID in .env or the environment")
    client.vector_stores.retrieve(store_id)
    LOG.info("Vector Store ID: %s", store_id)
    return store_id


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    requested = os.getenv("OPENAI_VECTOR_STORE_ID", "").strip()
    if not requested:
        raise SystemExit("Set OPENAI_VECTOR_STORE_ID in .env or the environment")
    articles_dir = Path(os.getenv("ARTICLES_DIR", "articles"))
    log_path = Path(os.getenv("INGESTION_LOG_PATH", "logs/ingestion.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )
    articles = sorted(articles_dir.glob("*.md"))
    if not articles:
        raise SystemExit(f"No Markdown files found in {articles_dir.resolve()}")
    # Coordinate local uploaders reading the same article directory.
    with (articles_dir / ".upload.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another uploader is using this article directory") from None
        with OpenAI(timeout=60, max_retries=5) as client:
            store_id = resolve_store(client, requested)
            counts = synchronize(client, store_id, articles)
    LOG.info("Summary: articles=%d uploaded=%d skipped=%d failed=%d "
             "embedded_files=%d embedded_chunks_estimated=%d vector_store_id=%s",
             len(articles), counts["uploaded"], counts["skipped"], counts["failed"],
             counts["embedded_files"], counts["embedded_chunks_estimated"], store_id)
    LOG.info("Delta: added=%d updated=%d skipped=%d failed=%d",
             counts["added"], counts["updated"], counts["skipped"], counts["failed"])
    summary_path = os.getenv("UPLOAD_SUMMARY_PATH")
    if summary_path:
        Path(summary_path).write_text(json.dumps({**counts, "vector_store_id": store_id}) + "\n")
    print(f"Vector Store ID: {store_id}")
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
