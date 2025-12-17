#!/usr/bin/env python3

"""
Quick status script for Knowledge Bob's vector brains.

Shows point counts for all known knowledge collections in Qdrant.
Safe to run while ingesters (PLOS, arXiv, Wikipedia) are working.
"""

from typing import List
from qdrant_client import QdrantClient

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333

# Collections we care about – some may not exist yet, that's fine.
COLLECTIONS: List[str] = [
    "knowledge_bob_plos",
    "knowledge_bob",
    "knowledge_bob_arxiv",
    "knowledge_bob_wikipedia",
]

def main() -> None:
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        timeout=30.0,
    )

    print(f"=== Knowledge Bob – Qdrant Status ({QDRANT_HOST}:{QDRANT_PORT}) ===")

    # Discover what's actually there
    existing = {c.name for c in client.get_collections().collections}
    print(f"Existing collections: {sorted(existing)}\n")

    for name in COLLECTIONS:
        if name not in existing:
            print(f"[{name}] does not exist yet.")
            continue

        try:
            res = client.count(
                collection_name=name,
                exact=True,
            )
            count = res.count if hasattr(res, "count") else res
            print(f"[{name}] points: {count}")
        except Exception as e:
            print(f"[{name}] error while counting: {e}")

if __name__ == "__main__":
    main()
