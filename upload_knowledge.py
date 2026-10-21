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

# Settings are strings loaded from .env (existing environment values take precedence).
load_dotenv()
ARTICLES_DIR = os.getenv("ARTICLES_DIR", "articles")
INGESTION_LOG_PATH = os.getenv("INGESTION_LOG_PATH", "logs/ingestion.log")
INGESTION_STATE_PATH = os.getenv("INGESTION_STATE_PATH", ".ingestion-state.json")
OPENAI_VECTOR_STORE_ID = os.getenv("OPENAI_VECTOR_STORE_ID") or None

LOG = logging.getLogger("optibot.ingestion")
MANAGER = "optibot-articles-v1"


def article_key(path: Path) -> str:
    """Exporter filenames end in the stable Zendesk ID, even after a rename."""
    match = re.search(r"-(\d+)$", path.stem)
    return match.group(1) if match else path.name


def synchronize(client, store_id: str, articles: list[Path]) -> dict[str, int]:
    counts = dict(uploaded=0, skipped=0, failed=0)
    existing = defaultdict(list)
    # SDK iteration follows every page. Only touch files owned by this uploader.
    for file in client.vector_stores.files.list(vector_store_id=store_id):
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

            # Retry also cleans an interrupted replacement: matching hashes skip
            # upload, but obsolete managed attachments are still removed.
            for old in previous:
                if old.id != current.id:
                    client.vector_stores.files.delete(old.id, vector_store_id=store_id)
            counts[action] += 1
            LOG.info("id=%s file=%s bytes=%d status=%s", key, path.name, len(content), action)
        except Exception:
            counts["failed"] += 1
            LOG.exception("id=%s file=%s status=failed", key, path.name)
    return counts


def resolve_store(client, state_path: Path, requested: str | None) -> str:
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    saved = state.get("vector_store_id")
    if requested and saved and requested != saved:
        raise ValueError("Store differs from saved state; use a different INGESTION_STATE_PATH")
    store_id = requested or saved
    if store_id:
        client.vector_stores.retrieve(store_id)
    else:
        store_id = client.vector_stores.create(name="OptiBot Support Knowledge Base").id
    # Save before uploading so a failed run reuses the same store next time.
    LOG.info("Vector Store ID: %s", store_id)
    temporary = state_path.with_name(state_path.name + ".tmp")
    temporary.write_text(json.dumps({"vector_store_id": store_id}) + "\n", encoding="utf-8")
    temporary.replace(state_path)
    return store_id


def main():
    articles_dir = Path(ARTICLES_DIR)
    log_path = Path(INGESTION_LOG_PATH)
    state_path = Path(INGESTION_STATE_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )
    articles = sorted(articles_dir.glob("*.md"))
    if not articles:
        raise SystemExit(f"No Markdown files found in {articles_dir.resolve()}")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Avoid simultaneous runs using this state file uploading the same articles.
    with state_path.with_name(state_path.name + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another uploader is using this state file") from None
        with OpenAI(timeout=60, max_retries=5) as client:
            store_id = resolve_store(client, state_path, OPENAI_VECTOR_STORE_ID)
            counts = synchronize(client, store_id, articles)
    LOG.info("Summary: articles=%d uploaded=%d skipped=%d failed=%d vector_store_id=%s",
             len(articles), counts["uploaded"], counts["skipped"], counts["failed"], store_id)
    print(f"Vector Store ID: {store_id}")
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
