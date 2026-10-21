#!/usr/bin/env python3
"""Export public English articles, optionally limiting API records processed."""

import argparse
import hashlib
import logging
from pathlib import Path

from src.client import iter_articles, make_session
from src.convert import article_to_markdown
from src.slug import article_slug

# Edit these settings, then run: python scrape.py
LIMIT = 6  # All articles; use a positive integer such as 30 for a limit.
OUT_DIR = "out"  # Output folder, relative to your current working directory.

LOG = logging.getLogger(__name__)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def article_status(target, article_id, data):
    """Compare full Markdown bytes with the previous export, matching by ID."""
    target_exists = target.exists()
    previous = target if target_exists else next(
        iter(sorted(target.parent.glob(f"*-{int(article_id)}.md"))), None
    )
    if previous is None:
        return "new"
    # A matching article at an old path still needs a write at the new path.
    if not target_exists:
        return "updated"
    old_hash = hashlib.sha256(previous.read_bytes()).digest()
    new_hash = hashlib.sha256(data).digest()
    return "unchanged" if old_hash == new_hash else "updated"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=positive_int, default=LIMIT)
    parser.add_argument("--out", type=Path, default=Path(OUT_DIR))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    fetched = skipped = failed = written = 0
    statuses = {"new": 0, "updated": 0, "unchanged": 0}
    seen = set()
    try:
        with make_session() as session:
            for article in iter_articles(session, limit=args.limit):
                fetched += 1
                try:
                    article_id = article["id"]
                    if article.get("draft") or article_id in seen:
                        skipped += 1
                        LOG.info("id=%s skipped=draft-or-duplicate", article_id)
                        continue
                    slug = article_slug(article["title"], article_id)
                    data = article_to_markdown(article).encode("utf-8")
                    # Replace atomically; remove an old filename if the title changed.
                    target = args.out / f"{slug}.md"
                    status = article_status(target, article_id, data)
                    if status != "unchanged":
                        temporary = target.with_suffix(".tmp")
                        temporary.write_bytes(data)
                        temporary.replace(target)
                        written += 1
                    for old in args.out.glob(f"*-{int(article_id)}.md"):
                        if old != target:
                            old.unlink()
                    seen.add(article_id)
                    statuses[status] += 1
                    LOG.info("id=%s slug=%s bytes=%s status=%s", article_id, slug, len(data), status)
                except Exception:
                    failed += 1
                    LOG.exception("id=%s failed", article.get("id", "unknown"))
    except Exception:
        failed += 1
        LOG.exception("API fetch failed; existing output retained")
    LOG.info(
        "Summary: fetched=%s skipped=%s failed=%s written=%s new=%s updated=%s unchanged=%s",
        fetched, skipped, failed, written,
        statuses["new"], statuses["updated"], statuses["unchanged"],
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
