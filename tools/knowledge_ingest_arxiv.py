#!/usr/bin/env python3

"""
Knowledge Bob - arXiv Ingestion Script

Streams the arxiv-metadata-oai-snapshot.json file (JSONL-style: one JSON
object per line) and ingests title + abstract into a dedicated Qdrant
collection: 'knowledge_bob_arxiv'.

Each chunk is tagged with:
  - source = 'arxiv'
  - source_trust = 'medium'

IMPORTANT: Only run this AFTER PLOS ingestion has finished, to avoid
overloading Qdrant.
"""

import os
import time
import uuid
import json
from datetime import datetime
from typing import List, Dict, Any

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models


# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

ARXIV_JSON_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../data/brains/knowledge_bob/sources/arxiv/metadata/arxiv-metadata-oai-snapshot.json",
    )
)

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "knowledge_bob_arxiv"

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBEDDING_VECTOR_SIZE = 768
COUNCIL_NAME = "knowledge_bob"

BATCH_SIZE_POINTS = 128   # points per upsert
EMBED_BATCH_SIZE = 128    # texts per embed call


# ------------------------------------------------------------
# Placeholder Embedder (replace with real BGE/E5 model)
# ------------------------------------------------------------

class LocalEmbedder:
    """
    Real embedding model using SentenceTransformers (BGE/E5-type).
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        print(f"[Embedder] Initializing {model_name} on {device}...")
        self.model = SentenceTransformer(model_name)
        self.model.to(device)
        self.vector_size = self.model.get_sentence_embedding_dimension()
        print(f"[Embedder] Loaded. Vector size = {self.vector_size}")

    def embed_batch(self, texts):
        print(f"[Embedder] Embedding batch: {len(texts)} items")
        emb = self.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
        )
        return emb.tolist()


# ------------------------------------------------------------
# Qdrant helpers
# ------------------------------------------------------------

def ensure_qdrant_collection(client: QdrantClient):
    print(f"[Qdrant][arXiv] Checking collection '{COLLECTION_NAME}'")
    collections = client.get_collections().collections
    names = {c.name for c in collections}

    if COLLECTION_NAME in names:
        print("[Qdrant][arXiv] Collection already exists.")
        return

    print("[Qdrant][arXiv] Creating collection...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=EMBEDDING_VECTOR_SIZE,
            distance=models.Distance.COSINE,
        ),
    )
    print("[Qdrant][arXiv] Collection created.")


def upsert_chunks(
    client: QdrantClient,
    embedder: LocalEmbedder,
    chunks: List[Dict[str, Any]],
):
    if not chunks:
        return

    total = len(chunks)
    print(f"[Ingest][arXiv] Upserting {total} chunks...")

    texts = [c["content"] for c in chunks]

    for i in range(0, total, BATCH_SIZE_POINTS):
        batch = chunks[i:i + BATCH_SIZE_POINTS]
        batch_texts = texts[i:i + BATCH_SIZE_POINTS]

        vectors = embedder.embed_batch(batch_texts)

        points = []
        for c, v in zip(batch, vectors):
            pid = int(uuid.uuid4().int >> 64)
            payload = {
                "section": c.get("section"),
                "source_file": c.get("source_file"),
                "chunk_id": c.get("chunk_id"),
                "document_title": c.get("document_title"),
                "council": c.get("council", COUNCIL_NAME),
                "timestamp": c.get("timestamp", int(time.time())),
                "mode": c.get("mode", "arxiv_abstract"),
                "source": "arxiv",
                "source_trust": "medium",
                "arxiv_id": c.get("arxiv_id"),
                "categories": c.get("categories"),
            }
            points.append(
                models.PointStruct(
                    id=pid,
                    vector=v,
                    payload=payload,
                )
            )

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=False,  # don't block on full persistence
        )
        print(
            f"[Ingest][arXiv] Upserted "
            f"{min(i + BATCH_SIZE_POINTS, total)}/{total} chunks"
        )


# ------------------------------------------------------------
# arXiv JSONL parsing & chunking
# ------------------------------------------------------------

def build_chunk_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given one arXiv metadata record, build a single chunk combining
    title + abstract (+ categories).
    """
    title = (record.get("title") or "").strip()
    abstract = (record.get("abstract") or "").strip()
    categories = record.get("categories") or ""
    arxiv_id = record.get("id") or ""

    if not title and not abstract:
        return {}

    cat_text = f"Categories: {categories}" if categories else ""
    preamble_parts = [p for p in [f"Title: {title}", cat_text] if p]
    preamble = ". ".join(preamble_parts)
    if preamble:
        preamble += ". "

    content = f"{preamble}Abstract: {abstract}" if abstract else preamble

    ts = int(time.time())
    source_file = f"arxiv:{arxiv_id or title or 'unknown'}"

    chunk = {
        "content": content,
        "section": "abstract",
        "document_title": title or f"arXiv:{arxiv_id}",
        "source_file": source_file,
        "mode": "arxiv_abstract",
        "chunk_id": f"{arxiv_id or title}_0",
        "timestamp": ts,
        "council": COUNCIL_NAME,
        "arxiv_id": arxiv_id,
        "categories": categories,
    }
    return chunk


def iter_arxiv_records(json_path: str):
    """
    Stream records from the arxiv-metadata-oai-snapshot.json file.

    The file is JSONL-style: one JSON object per line.
    """
    print(f"[Parse][arXiv] Streaming records from {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"[Parse][arXiv] JSON decode error at line {idx}, skipping.")
                continue
            yield idx, record


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    print(
        f"--- Knowledge Bob arXiv Ingestion Start "
        f"({datetime.now().isoformat()}) ---"
    )
    print(f"[Config][arXiv] JSON PATH: {ARXIV_JSON_PATH}")

    if not os.path.isfile(ARXIV_JSON_PATH):
        print("[Error][arXiv] Metadata JSON file not found.")
        return

    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        timeout=60.0,
    )
    embedder = LocalEmbedder(EMBEDDING_MODEL_NAME)

    # Recreate collection with actual vector size from embedder
    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=embedder.vector_size,
            distance=models.Distance.COSINE,
        ),
    )
    print(f"[Qdrant][arXiv] Collection '{COLLECTION_NAME}' recreated.")

    buffer: List[Dict[str, Any]] = []
    BUFFER_LIMIT = 512  # chunks before flushing to Qdrant

    total_records = 0
    kept_records = 0

    for idx, record in iter_arxiv_records(ARXIV_JSON_PATH):
        total_records += 1
        chunk = build_chunk_from_record(record)
        if not chunk:
            continue

        buffer.append(chunk)
        kept_records += 1

        if idx % 10_000 == 0:
            print(
                f"[Ingest][arXiv] Seen {idx} lines, "
                f"kept {kept_records} records so far. "
                f"Buffer size={len(buffer)}"
            )

        if len(buffer) >= BUFFER_LIMIT:
            upsert_chunks(client, embedder, buffer)
            buffer.clear()

    # Flush any remaining
    if buffer:
        upsert_chunks(client, embedder, buffer)
        buffer.clear()

    print(
        f"[Ingest][arXiv] Finished. "
        f"Total records seen: {total_records}, "
        f"kept: {kept_records}"
    )
    print("--- Knowledge Bob arXiv Ingestion Complete ---")


if __name__ == "__main__":
    main()
