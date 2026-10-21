"""Public Zendesk API client."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ARTICLES_URL = (
    "https://support.optisigns.com/api/v2/help_center/en-us/articles.json?page[size]=10"
)


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = "OptiSignsMarkdownExport/1.0"
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def iter_articles(session, url=ARTICLES_URL, limit=None):
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")

    seen = set()
    yielded = 0
    while url:
        if url in seen:
            raise ValueError(f"Pagination loop: {url}")
        seen.add(url)
        response = session.get(url, timeout=(10, 60))
        response.raise_for_status()
        page = response.json()
        if not isinstance(page.get("articles"), list):
            raise ValueError("API response is missing an articles list")
        for article in page["articles"]:
            yield article
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        has_more = page["meta"]["has_more"]
        if not isinstance(has_more, bool):
            raise ValueError("API response has an invalid meta.has_more value")
        if not has_more:
            return
        url = page["links"].get("next")
        if not isinstance(url, str) or not url:
            raise ValueError("API response has_more is true but links.next is missing")
