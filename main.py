#!/usr/bin/env python3
"""Scrape articles, then upload them to the configured knowledge store."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from dotenv import load_dotenv

from scrape import positive_int


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=positive_int,
                        help="Override LIMIT from the environment or .env")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    env = os.environ.copy()
    if not env.get("OPENAI_API_KEY", "").strip():
        parser.error("Set OPENAI_API_KEY in .env or the environment")
    env.setdefault("ARTICLES_DIR", "articles")
    command = [sys.executable, str(root / "scrape.py"), "--out", env["ARTICLES_DIR"]]
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])

    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "stage": "scrape", "added": None,
              "updated": None, "skipped": None}
    artifact = Path(env.get("RUN_ARTIFACT_PATH", "logs/last-run.json"))
    try:
        with tempfile.TemporaryDirectory(prefix="darkharvest-") as temporary:
            summary = Path(temporary) / "upload.json"
            env["UPLOAD_SUMMARY_PATH"] = str(summary)
            print("Scraping articles...", flush=True)
            result = subprocess.run(command, env=env)
            report["exit_code"] = result.returncode
            if result.returncode:
                print("Scrape failed; upload skipped.", file=sys.stderr)
                return result.returncode
            report["stage"] = "upload"
            print("Uploading knowledge...", flush=True)
            result = subprocess.run(
                [sys.executable, str(root / "upload_knowledge.py")], env=env,
            )
            report["exit_code"] = result.returncode
            if summary.exists():
                report.update(json.loads(summary.read_text()))
            report["status"] = "success" if result.returncode == 0 else "failed"
            return result.returncode
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        artifact.parent.mkdir(parents=True, exist_ok=True)
        temporary_report = artifact.with_suffix(".tmp")
        temporary_report.write_text(json.dumps(report, indent=2) + "\n")
        temporary_report.replace(artifact)
        print("Run summary: " + json.dumps(report), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
