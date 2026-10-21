#!/usr/bin/env python3
"""Scrape articles, then upload them to the configured knowledge store."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv

from scrape import positive_int


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=positive_int,
                        help="Override the article limit configured in scrape.py")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    env = os.environ.copy()
    env.setdefault("ARTICLES_DIR", "articles")
    command = [sys.executable, str(root / "scrape.py"), "--out", env["ARTICLES_DIR"]]
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])

    print("Scraping articles...", flush=True)
    result = subprocess.run(command, env=env)
    if result.returncode:
        print("Scrape failed; upload skipped.", file=sys.stderr)
        return result.returncode

    print("Uploading knowledge...", flush=True)
    return subprocess.run(
        [sys.executable, str(root / "upload_knowledge.py")], env=env,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
