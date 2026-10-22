import json
from pathlib import Path
import tempfile
import os
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from main import main


class MainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.artifact = Path(temporary.name) / "run.json"
        patcher = patch.dict(os.environ, {"RUN_ARTIFACT_PATH": str(self.artifact),
                                          "OPENAI_API_KEY": "test-key",
                                          "OPENAI_VECTOR_STORE_ID": "vs-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("main.load_dotenv")
    @patch("main.subprocess.run")
    def test_artifact_contains_upload_counts(self, run, load):
        def execute(command, env):
            if command[1].endswith("upload_knowledge.py"):
                Path(env["UPLOAD_SUMMARY_PATH"]).write_text(json.dumps(
                    {"added": 2, "updated": 1, "skipped": 27, "failed": 0}))
            return CompletedProcess(command, 0)
        run.side_effect = execute
        self.assertEqual(main([]), 0)
        result = json.loads(self.artifact.read_text())
        self.assertEqual((result["added"], result["updated"], result["skipped"]), (2, 1, 27))
        self.assertEqual(result["status"], "success")

    @patch("main.load_dotenv")
    @patch("main.subprocess.run", side_effect=OSError("cannot start"))
    def test_exception_writes_failed_artifact(self, run, load):
        with self.assertRaises(OSError):
            main([])
        result = json.loads(self.artifact.read_text())
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["added"])

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

    @patch("main.load_dotenv")
    @patch.dict(os.environ, {"OPENAI_VECTOR_STORE_ID": " "})
    @patch("main.subprocess.run")
    def test_missing_store_allows_pipeline(self, run, load):
        run.return_value.returncode = 0
        self.assertEqual(main([]), 0)
        self.assertEqual(run.call_count, 2)

    @patch("main.load_dotenv")
    @patch.dict(os.environ, {"OPENAI_API_KEY": " "})
    @patch("main.subprocess.run")
    def test_missing_api_key_stops_before_scraping(self, run, load):
        with self.assertRaises(SystemExit) as error:
            main([])
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()

    @patch("main.subprocess.run")
    def test_store_id_loaded_from_dotenv(self, run):
        root = self.artifact.parent
        (root / ".env").write_text("OPENAI_VECTOR_STORE_ID=vs-from-dotenv\n")
        run.return_value.returncode = 0
        with patch.dict(os.environ):
            os.environ.pop("OPENAI_VECTOR_STORE_ID", None)
            with patch("main.__file__", str(root / "main.py")):
                self.assertEqual(main([]), 0)
        self.assertEqual(run.call_args.kwargs["env"]["OPENAI_VECTOR_STORE_ID"],
                         "vs-from-dotenv")
