from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.client import ARTICLES_URL, iter_articles, make_session
from src.convert import html_to_markdown
from src.slug import article_slug
import scrape

FIXTURES = Path(__file__).parent / "fixtures"


class ConvertTests(unittest.TestCase):
    def test_fixture(self):
        self.assertEqual(
            html_to_markdown((FIXTURES / "article.html").read_text()),
            (FIXTURES / "article.md").read_text(),
        )

    def test_code_whitespace_and_embedded_fence(self):
        code = '  first  \n\n\n\n\tsecond\n```\n'
        self.assertEqual(
            html_to_markdown(f"<pre><code>{code}</code></pre>"),
            f"````\n{code}````\n",
        )

    def test_prose_cleanup_and_css_pixel(self):
        self.assertEqual(
            html_to_markdown('<p>Hello  </p><p></p><img src="pixel" style="width: 1px; height: 1px">'),
            "Hello\n",
        )


class SlugTests(unittest.TestCase):
    def test_collisions(self):
        self.assertNotEqual(article_slug("Same!", 1), article_slug("Same?", 2))
        self.assertEqual(article_slug("Same!", 1), article_slug("Same!", 1))

    def test_unicode(self):
        self.assertEqual(article_slug("Café 中文", 42), "café-中文-42")
        self.assertLess(len(article_slug("中" * 300, 42).encode()), 255)

    def test_empty_title(self):
        self.assertEqual(article_slug("!!!", 3), "article-3")
        self.assertEqual(article_slug("", 3), "article-3")


class ClientTests(unittest.TestCase):
    def test_two_pages(self):
        session = Mock()
        next_url = "https://example.org/articles?page%5Bafter%5D=opaque%3D&page%5Bsize%5D=100"
        session.get.side_effect = [
            Mock(json=Mock(return_value={
                "articles": [{"id": 1}], "meta": {"has_more": True},
                "links": {"next": next_url},
            })),
            Mock(json=Mock(return_value={
                "articles": [{"id": 2}], "meta": {"has_more": False},
                "links": {"next": "https://example.org/do-not-follow"},
            })),
        ]
        self.assertEqual(list(iter_articles(session)), [{"id": 1}, {"id": 2}])
        self.assertIn("page[size]=100", ARTICLES_URL)
        self.assertEqual(session.get.call_args_list[0].args[0], ARTICLES_URL)
        self.assertEqual(session.get.call_args_list[1].args[0], next_url)
        self.assertEqual(session.get.call_count, 2)
        for call in session.get.call_args_list:
            self.assertEqual(call.kwargs["timeout"], (10, 60))

    def test_pagination_loop(self):
        session = Mock()
        session.get.return_value.json.return_value = {
            "articles": [], "meta": {"has_more": True}, "links": {"next": "same"},
        }
        with self.assertRaisesRegex(ValueError, "Pagination loop"):
            list(iter_articles(session, "same"))

    def test_empty_terminal_page(self):
        session = Mock()
        session.get.side_effect = [
            Mock(json=Mock(return_value={
                "articles": [{"id": 1}], "meta": {"has_more": True},
                "links": {"next": "https://example.org/end"},
            })),
            Mock(json=Mock(return_value={
                "articles": [], "meta": {"has_more": False, "after_cursor": None},
                "links": {"next": None},
            })),
        ]
        self.assertEqual(list(iter_articles(session)), [{"id": 1}])
        self.assertEqual(session.get.call_count, 2)

    def test_missing_next_link_does_not_silently_truncate(self):
        session = Mock()
        session.get.return_value.json.return_value = {
            "articles": [], "meta": {"has_more": True}, "links": {"next": None},
        }
        with self.assertRaisesRegex(ValueError, "links.next is missing"):
            list(iter_articles(session))

    def test_invalid_has_more(self):
        session = Mock()
        session.get.return_value.json.return_value = {
            "articles": [], "meta": {"has_more": "false"}, "links": {},
        }
        with self.assertRaisesRegex(ValueError, "invalid meta.has_more"):
            list(iter_articles(session))

    def test_retry_policy(self):
        with make_session() as session:
            retry = session.get_adapter("https://").max_retries
            self.assertIn(429, retry.status_forcelist)
            self.assertTrue(retry.respect_retry_after_header)
            self.assertGreater(retry.backoff_factor, 0)
            response = Mock(headers={"Retry-After": "2"})
            self.assertEqual(retry.get_retry_after(response), 2)


class CliTests(unittest.TestCase):
    def test_isolation_drafts_duplicates_and_rerun(self):
        good = dict(id=1, title="Example", body="<p>Body</p>",
                    html_url="https://example.org/1", updated_at="2026-10-20")
        bad = dict(good, id=2, body=None)
        draft = dict(good, id=3, draft=True)
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.argv", ["scrape.py", "--out", directory]), \
                 patch("scrape.iter_articles", return_value=iter([bad, draft, good, good])), \
                 self.assertLogs(level="INFO") as logs:
                self.assertEqual(scrape.main(), 1)
            self.assertIn("fetched=4 skipped=2 failed=1 written=1", logs.output[-1])
            with patch("sys.argv", ["scrape.py", "--out", directory]), \
                 patch("scrape.iter_articles", return_value=iter([dict(good, title="Renamed")])), \
                 self.assertLogs(level="INFO"):
                self.assertEqual(scrape.main(), 0)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["renamed-1.md"])


if __name__ == "__main__":
    unittest.main()
