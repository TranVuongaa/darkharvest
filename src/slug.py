"""Deterministic filenames with article IDs for uniqueness."""

import re
import unicodedata


def article_slug(title, article_id):
    title = unicodedata.normalize("NFKC", title).casefold()
    title = re.sub(r"[^\w]+", "-", title, flags=re.UNICODE)
    title = title.replace("_", "-").strip("-")
    # Bound UTF-8 filename length, leaving room for the ID and extension.
    title = title.encode("utf-8")[:160].decode("utf-8", errors="ignore").rstrip("-")
    return f"{title or 'article'}-{int(article_id)}"
