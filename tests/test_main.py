import os
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from main import main


class MainTests(unittest.TestCase):
    @patch("main.load_dotenv")
    @patch.dict(os.environ, {"ARTICLES_DIR": "custom articles"})
    @patch("main.subprocess.run")
    def test_scrape_then_upload_with_shared_directory(self, run, load):
        run.return_value.returncode = 0
        self.assertEqual(main(["--limit", "30"]), 0)
        scrape, upload = run.call_args_list
        self.assertTrue(scrape.args[0][1].endswith("/scrape.py"))
        self.assertEqual(scrape.args[0][2:], ["--out", "custom articles", "--limit", "30"])
        self.assertTrue(upload.args[0][1].endswith("/upload_knowledge.py"))
        self.assertEqual(scrape.kwargs["env"], upload.kwargs["env"])

    @patch("main.load_dotenv")
    @patch("main.subprocess.run")
    def test_scrape_failure_prevents_upload(self, run, load):
        run.return_value.returncode = 1
        self.assertEqual(main([]), 1)
        run.assert_called_once()
        self.assertNotIn("--limit", run.call_args.args[0])

    @patch("main.load_dotenv")
    @patch("main.subprocess.run")
    def test_upload_failure_is_returned(self, run, load):
        run.side_effect = [CompletedProcess([], 0), CompletedProcess([], 2)]
        self.assertEqual(main([]), 2)
