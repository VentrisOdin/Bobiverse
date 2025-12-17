#!/usr/bin/env python3
"""
PLOS Resume Helper

- Shows Qdrant point counts for knowledge_bob_plos
- Suggests next PLOS_START_INDEX (and optional PLOS_END_INDEX window)

It can determine the last processed index via:
  1) a progress JSON file (recommended) OR
  2) parsing an ingestion log file you provide

Usage examples:
  python plos_resume_helper.py
  python plos_resume_helper.py --log-file /path/to/plos_ingest.log
  python plos_resume_helper.py --log-file /path/to/plos_ingest.log --window 5000
  python plos_resume_helper.py --progress-file tools/plos_ingest_progress.json --window 5000
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from qdrant_client import QdrantClient


DEFAULT_COLLECTION = "knowledge_bob_plos"
DEFAULT_QDRANT_HOST = "localhost"
DEFAULT_QDRANT_PORT = 6333

# Matches:
#   [Ingest] Progress: 10794/391477 files complete
RE_PROGRESS = re.compile(r"Progress:\s+(\d+)/(\d+)\s+files\s+complete", re.IGNORECASE)

# Matches:
#   [Ingest] === File 13763/391477 === journal.pone.0011529.xml
RE_FILE = re.compile(r"===\s*File\s+(\d+)/(\d+)\s*===", re.IGNORECASE)


def qdrant_counts(host: str, port: int, collection: str) -> Tuple[bool, Optional[int]]:
    client = QdrantClient(host=host, port=port, timeout=10.0)

    try:
        cols = {c.name for c in client.get_collections().collections}
    except Exception as e:
        print(f"[Qdrant] ERROR: cannot reach Qdrant at {host}:{port}: {e}")
        return False, None

    if collection not in cols:
        print(f"[Qdrant] Collection '{collection}' does not exist.")
        print(f"[Qdrant] Existing collections: {sorted(cols)}")
        return True, None

    try:
        info = client.get_collection(collection)
        # points_count exists on recent Qdrant; if not, fallback to None
        points = getattr(info, "points_count", None)
        if points is None and hasattr(info, "result") and hasattr(info.result, "points_count"):
            points = info.result.points_count
    except Exception as e:
        print(f"[Qdrant] ERROR: cannot get collection info: {e}")
        return True, None

    return True, int(points) if points is not None else None


def read_progress_file(progress_file: Path) -> Tuple[Optional[int], Optional[int]]:
    """
    Expected JSON structure:
      {
        "last_completed_index": 13762,
        "total_files": 391477,
        "last_file": "journal.pone.0011529.xml",
        "updated_ts": 1730000000
      }
    """
    if not progress_file.exists():
        return None, None

    try:
        data = json.loads(progress_file.read_text(encoding="utf-8"))
        last_idx = int(data.get("last_completed_index")) if data.get("last_completed_index") is not None else None
        total = int(data.get("total_files")) if data.get("total_files") is not None else None
        return last_idx, total
    except Exception as e:
        print(f"[Progress] Could not parse progress file {progress_file}: {e}")
        return None, None


def parse_log_file(log_file: Path) -> Tuple[Optional[int], Optional[int]]:
    if not log_file.exists():
        print(f"[Log] Log file not found: {log_file}")
        return None, None

    last_idx = None
    total_files = None

    try:
        # Read a tail chunk (fast) — last ~2MB
        with log_file.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(size - 2_000_000, 0), os.SEEK_SET)
            tail = f.read().decode("utf-8", errors="ignore")

        # Prefer "Progress:" lines (they represent completed count)
        for m in RE_PROGRESS.finditer(tail):
            last_idx = int(m.group(1))
            total_files = int(m.group(2))

        # If no progress lines found, fall back to "=== File X/..." lines
        if last_idx is None:
            for m in RE_FILE.finditer(tail):
                last_idx = int(m.group(1)) - 1  # the file line is "currently processing", so completed is -1
                total_files = int(m.group(2))

        return last_idx, total_files
    except Exception as e:
        print(f"[Log] Failed reading/parsing log file {log_file}: {e}")
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qdrant-host", default=DEFAULT_QDRANT_HOST)
    ap.add_argument("--qdrant-port", type=int, default=DEFAULT_QDRANT_PORT)
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)

    ap.add_argument("--progress-file", default="tools/plos_ingest_progress.json",
                    help="JSON file written by ingester (recommended).")
    ap.add_argument("--log-file", default=None,
                    help="Path to an ingest log file to parse (works immediately if you tee output).")
    ap.add_argument("--window", type=int, default=0,
                    help="If set (>0), suggests PLOS_END_INDEX = start + window - 1.")

    args = ap.parse_args()

    print("=== PLOS Resume Helper ===")

    ok, points = qdrant_counts(args.qdrant_host, args.qdrant_port, args.collection)
    if ok:
        if points is not None:
            print(f"[Qdrant] {args.collection} points_count: {points:,}")
        else:
            print(f"[Qdrant] {args.collection} points_count: (unknown)")

    progress_path = Path(args.progress_file)
    last_idx, total_files = read_progress_file(progress_path)

    source = None
    if last_idx is not None:
        source = f"progress_file:{progress_path}"
    else:
        if args.log_file:
            log_path = Path(args.log_file)
            last_idx, total_files = parse_log_file(log_path)
            if last_idx is not None:
                source = f"log_file:{log_path}"

    if last_idx is None:
        print("[Resume] Could not determine last completed index.")
        print("[Resume] Tip: run ingestion with tee so we can parse logs, e.g.:")
        print("        PLOS_START_INDEX=... python tools/knowledge_ingest.py 2>&1 | tee -a /tmp/plos_ingest.log")
        print("[Resume] Or add progress writing to the ingester and use --progress-file.")
        return

    next_start = last_idx + 1
    print(f"[Resume] Last completed index: {last_idx} (source={source})")
    if total_files:
        print(f"[Resume] Total files (from source): {total_files}")

    if args.window and args.window > 0:
        end_idx = next_start + args.window - 1
        if total_files:
            end_idx = min(end_idx, total_files)
        print("\nSuggested next run (windowed):")
        print(f"  PLOS_START_INDEX={next_start} PLOS_END_INDEX={end_idx} python tools/knowledge_ingest.py")
    else:
        print("\nSuggested next run:")
        print(f"  PLOS_START_INDEX={next_start} python tools/knowledge_ingest.py")


if __name__ == "__main__":
    main()

