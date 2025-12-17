#!/usr/bin/env python3

"""
Tag existing Qdrant collections with trust metadata.

This does NOT modify vectors or re-embed anything.
It simply updates payloads for each point with:

- source       (e.g., 'plos', 'wikipedia')
- source_trust (e.g., 'high', 'low')

Run this AFTER PLOS and Wikipedia ingestion finishes.
"""

from qdrant_client import QdrantClient
from typing import Dict, Any

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333

# Collections and their trust levels
COLLECTIONS = {
    "knowledge_bob_plos": {
        "source": "plos",
        "source_trust": "high",
    },
    "knowledge_bob_wikipedia": {
        "source": "wikipedia",
        "source_trust": "low",
    },
}


def tag_collection(
    client: QdrantClient,
    collection_name: str,
    tags: Dict[str, Any],
    batch_size: int = 500,
):
    print(f"[Tagger] Tagging collection '{collection_name}' with:", tags)

    offset = None
    total = 0

    while True:
        # Scroll retrieves batches of points
        res, offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not res:
            break

        point_ids = [p.id for p in res]

        # Apply metadata tags to these points
        client.set_payload(
            collection_name=collection_name,
            payload=tags,
            points=point_ids,
        )

        total += len(point_ids)
        print(f"[Tagger] Updated payload for {total} points...")

        if offset is None:
            break

    print(f"[Tagger] Finished tagging '{collection_name}'. Total points updated: {total}")


def main():
    print("[Tagger] Connecting to Qdrant...")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    collections = client.get_collections().collections
    existing = {c.name for c in collections}

    print("[Tagger] Existing Qdrant collections:", existing)

    for coll_name, tags in COLLECTIONS.items():
        if coll_name not in existing:
            print(f"[Tagger] Skipping '{coll_name}' (does not exist).")
            continue

        tag_collection(client, coll_name, tags)


if __name__ == "__main__":
    main()

