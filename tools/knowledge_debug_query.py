#!/usr/bin/env python3

"""
Debug tool for Knowledge Bob RAG.

Uses the same Qdrant + embedder setup as the knowledge_council service
to show the top trust-weighted hits for a given query.
"""

import os
from typing import List, Dict, Any

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# Match knowledge_council_service settings
QDRANT_HOST = os.getenv("KNOWLEDGE_QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("KNOWLEDGE_QDRANT_PORT", "6333"))
EMBED_MODEL = os.getenv("KNOWLEDGE_EMBED_MODEL", "all-MiniLM-L6-v2")

COLLECTIONS_CONFIG: Dict[str, Dict[str, Any]] = {
    "knowledge_bob_plos": {"trust": "high", "weight": 1.0},
    "knowledge_bob": {"trust": "medium", "weight": 0.7},
    "knowledge_bob_arxiv": {"trust": "medium_high", "weight": 0.85},
    "knowledge_bob_wikipedia": {"trust": "low", "weight": 0.3},
}

TRUST_WEIGHTS: Dict[str, float] = {
    "very_high": 1.2,
    "high": 1.0,
    "medium_high": 0.85,
    "medium": 0.7,
    "low": 0.3,
}


def trust_weighted_search(
    qdrant_client: QdrantClient,
    embedder: SentenceTransformer,
    query: str,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    vec = embedder.encode([query])[0]
    all_hits: List[Dict[str, Any]] = []

    for coll_name, cfg in COLLECTIONS_CONFIG.items():
        try:
            res = qdrant_client.search(
                collection_name=coll_name,
                query_vector=vec,
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            continue

        trust_label = cfg.get("trust", "low")
        base_weight = cfg.get("weight") or TRUST_WEIGHTS.get(trust_label, 0.3)

        for r in res:
            payload = r.payload or {}
            base_score = float(r.score)
            final_score = base_score * float(base_weight)
            all_hits.append(
                {
                    "collection": coll_name,
                    "score": final_score,
                    "base_score": base_score,
                    "trust": trust_label,
                    "weight": base_weight,
                    "payload": payload,
                }
            )

    all_hits.sort(key=lambda h: h["score"], reverse=True)
    return all_hits[:top_k]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Debug Knowledge Bob trust-weighted search."
    )
    parser.add_argument("query", help="Question / search query")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60.0)
    embedder = SentenceTransformer(EMBED_MODEL)

    hits = trust_weighted_search(client, embedder, args.query, top_k=args.top_k)

    print(f"\n=== Top {len(hits)} hits for query: {args.query!r} ===\n")
    for i, h in enumerate(hits, start=1):
        p = h["payload"]
        title = p.get("document_title") or "Unknown title"
        section = p.get("section") or "Unknown section"
        source = p.get("source_file") or h["collection"]
        trust = h.get("trust")
        print(
            f"[{i}] {title}\n"
            f"    Source   : {source}\n"
            f"    Section  : {section}\n"
            f"    Collection: {h['collection']} | Trust: {trust}\n"
            f"    Score    : {h['score']:.4f} (base={h['base_score']:.4f}, weight={h['weight']})\n"
        )


if __name__ == "__main__":
    main()

