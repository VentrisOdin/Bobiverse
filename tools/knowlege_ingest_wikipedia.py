#!/usr/bin/env python3

"""
Knowledge Bob - Wikipedia Ingestion Script

Streams the giant enwiki XML dump and ingests pages into a separate
Qdrant collection: 'knowledge_bob_wikipedia'.

Each chunk is tagged with:
  - source = 'wikipedia'
  - source_trust = 'low'

IMPORTANT: Only run this AFTER PLOS ingestion has finished, to avoid
overloading Qdrant.
"""

import os
import time
import uuid
from datetime import datetime
from typing import List, Dict, Any, Iterable

import lxml.etree as ET
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models

# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

WIKI_XML_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../data/brains/knowledge_bob/sources/wikipedia/xml/enwiki-latest-pages-articles.xml",
    )
)

QDRANT_HOST = "localhost"

QDRANT_PORT = 6333
COLLECTION_NAME = "knowledge_bob_wikipedia"

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBEDDING_VECTOR_SIZE = 768
CHUNK_SIZE = 256     # smaller chunks for noisy wiki text
CHUNK_OVERLAP = 64
COUNCIL_NAME = "knowledge_bob"


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
    print(f"[Qdrant] Checking collection '{COLLECTION_NAME}'")
    collections = client.get_collections().collections
    names = {c.name for c in collections}

    if COLLECTION_NAME in names:
        print("[Qdrant] Collection already exists.")
        return

    print("[Qdrant] Creating collection...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=EMBEDDING_VECTOR_SIZE,
            distance=models.Distance.COSINE,
        ),
    )
    print("[Qdrant] Collection created.")


def upsert_chunks(
    client: QdrantClient,
    embedder: LocalEmbedder,
    chunks: List[Dict[str, Any]],
    batch_size: int = 64,
):
    if not chunks:
        return

    total = len(chunks)
    print(f"[Ingest][Wiki] Upserting {total} chunks...")

    texts = [c["content"] for c in chunks]

    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        batch_texts = texts[i:i + batch_size]

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
                "mode": c.get("mode", "wiki_page"),
                "source": "wikipedia",
                "source_trust": "low",
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
        print(f"[Ingest][Wiki] Upserted {min(i + batch_size, total)}/{total} chunks")


# ------------------------------------------------------------
# Wikipedia XML parsing
# ------------------------------------------------------------

def iter_wiki_pages(xml_path: str) -> Iterable[ET._Element]:
    """
    Stream through the Wikipedia dump, yielding <page> elements one by one.

    Uses iterparse to avoid loading the whole 90GB file into memory.
    """
    print(f"[Parse][Wiki] Streaming pages from {xml_path}")
    context = ET.iterparse(xml_path, events=("end",), tag="{*}page")

    for event, elem in context:
        yield elem
        # Clear element from memory
        elem.clear()
        # Also clear parent references to prevent memory leaks
        while elem.getprevious() is not None:
            del elem.getparent()[0]


def extract_page_text(page: ET._Element) -> Dict[str, Any]:
    """
    Extract title and raw wikitext from a <page> element.
    """
    ns = "{*}"
    title_el = page.find(f"{ns}title")
    title = title_el.text.strip() if title_el is not None and title_el.text else "Untitled"

    revision = page.find(f"{ns}revision")
    text_el = revision.find(f"{ns}text") if revision is not None else None
    raw_text = text_el.text or ""

    return {
        "title": title,
        "text": raw_text,
    }


def chunk_wiki_page(page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Chunk a Wikipedia page into smaller pieces. For v1 we will:
      - treat the whole article as one text body
      - split into token-ish chunks with overlap

    Later we can be smarter and split by headings and sections.
    """
    title = page_data["title"]
    text = page_data["text"]
    if not text.strip():
        return []

    tokens = text.split()
    chunks: List[Dict[str, Any]] = []

    i = 0
    idx = 0
    ts = int(time.time())
    source_file = f"wikipedia:{title}"

    while i < len(tokens):
        chunk_tokens = tokens[i:i + CHUNK_SIZE]
        chunk_text = " ".join(chunk_tokens)

        preamble = f"Article title: {title}. "
        full_content = preamble + chunk_text

        chunks.append(
            {
                "content": full_content,
                "section": "article",
                "document_title": title,
                "source_file": source_file,
                "mode": "wiki_page",
                "chunk_id": f"{title}_{idx}",
                "timestamp": ts,
                "council": COUNCIL_NAME,
            }
        )

        i += max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
        idx += 1

    return chunks


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    if not os.path.isfile(WIKI_XML_PATH):
        print("[Error][Wiki] Wikipedia XML file not found.")
        return

    client = QdrantClient(QDRANT_HOST, port=QDRANT_PORT)
    embedder = LocalEmbedder(EMBEDDING_MODEL_NAME)
    dim = embedder.vector_size

    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=dim,
            distance=models.Distance.COSINE,
        ),
    )

    print("Starting Wikipedia ingestion...")

    page_count = 0
    chunk_buffer: List[Dict[str, Any]] = []
    BUFFER_LIMIT = 512  # how many chunks to buffer before upsert

    for page in iter_wiki_pages(WIKI_XML_PATH):
        page_data = extract_page_text(page)
        chunks = chunk_wiki_page(page_data)

        if chunks:
            chunk_buffer.extend(chunks)

        page_count += 1

        if page_count % 1000 == 0:
            print(f"[Ingest][Wiki] Processed {page_count} pages, buffer size={len(chunk_buffer)}")

        # If buffer is large enough, flush to Qdrant
        if len(chunk_buffer) >= BUFFER_LIMIT:
            upsert_chunks(client, embedder, chunk_buffer)
            chunk_buffer.clear()

    # Flush remaining chunks
    if chunk_buffer:
        upsert_chunks(client, embedder, chunk_buffer)
        chunk_buffer.clear()

    print(f"[Ingest][Wiki] Finished. Total pages seen: {page_count}")
    print("--- Knowledge Bob Wikipedia Ingestion Complete ---")


if __name__ == "__main__":
    main()
