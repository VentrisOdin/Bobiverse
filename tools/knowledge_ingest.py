#!/usr/bin/env python3

import os
import time
from datetime import datetime
from typing import List, Dict, Any
import uuid
import lxml.etree as ET
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

PLOS_XML_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../data/brains/knowledge_bob/sources/plos/xml"
    )
)

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "knowledge_bob_plos"

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
# This will be overwritten at runtime by the model's actual dimension
EMBEDDING_VECTOR_SIZE = 768
CHUNK_SIZE = 512
CHUNK_OVERLAP = 100
COUNCIL_NAME = "knowledge_bob"

# ------------------------------------------------------------
# Placeholder Embedder (replace with real BGE/E5 embedder)
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

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        print(f"[Embedder] Embedding batch: {len(texts)} items")
        embeddings = self.model.encode(
            texts,
            batch_size=16,
            show_progress_bar=False,
        )
        return embeddings.tolist()

# ------------------------------------------------------------
# Qdrant: Create/Check Collection
# ------------------------------------------------------------

def create_qdrant_collection(client: QdrantClient):
    print(f"Checking collection '{COLLECTION_NAME}'...")
    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=EMBEDDING_VECTOR_SIZE,
            distance=models.Distance.COSINE,
        ),
    )
    print(f"Collection '{COLLECTION_NAME}' recreated successfully.")

# ------------------------------------------------------------
# XML Parsing + Chunking
# ------------------------------------------------------------

def parse_and_chunk_xml(xml_file: str) -> List[Dict[str, Any]]:
    chunks = []

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Extract title
        title_el = root.find(".//article-title")
        document_title = title_el.text.strip() if (title_el is not None and title_el.text) else os.path.basename(xml_file)

        # Provenance
        rel_path = os.path.relpath(xml_file, start=PLOS_XML_DIR)
        source_file = os.path.join("plos", "xml", rel_path)

        # Extract abstract
        def add_single_section(tag, section_name):
            sec = root.find(f".//{tag}")
            if sec is None:
                return
            parts = [(p.text or "").strip() for p in sec.findall(".//p") if p.text]
            text = " ".join(p for p in parts if p)
            if text:
                chunks.append({
                    "content": text,
                    "section": section_name,
                    "document_title": document_title,
                    "source_file": source_file,
                    "mode": "standalone"
                })

        add_single_section("abstract", "Abstract")

        # Main body sections
        body = root.find(".//body")
        if body is not None:
            for idx, sec in enumerate(body.findall(".//sec")):
                title_node = sec.find("./title")
                sec_title = title_node.text.strip() if (title_node is not None and title_node.text) else f"Section {idx+1}"

                paragraphs = [(p.text or "").strip() for p in sec.findall(".//p") if p.text]
                full_text = " ".join(p for p in paragraphs if p)
                if not full_text:
                    continue

                tokens = full_text.split()
                i = 0

                while i < len(tokens):
                    chunk_tokens = tokens[i:i+CHUNK_SIZE]
                    chunk_text = " ".join(chunk_tokens)
                    preamble = f"Document: {document_title}. Section: {sec_title}. "
                    chunks.append({
                        "content": preamble + chunk_text,
                        "section": sec_title,
                        "document_title": document_title,
                        "source_file": source_file,
                        "mode": "split"
                    })
                    i += max(CHUNK_SIZE - CHUNK_OVERLAP, 1)

    except Exception as e:
        print(f"[Parser] Error parsing {xml_file}: {e}")
        return []

    # Add metadata
    ts = int(time.time())
    final = []
    for idx, c in enumerate(chunks):
        c["chunk_id"] = f"{os.path.basename(xml_file)}_{idx}"
        c["timestamp"] = ts
        c["council"] = COUNCIL_NAME
        final.append(c)

    return final

# ------------------------------------------------------------
# Qdrant Upsert
# ------------------------------------------------------------

def upsert_chunks(client: QdrantClient, embedder: LocalEmbedder, chunks: List[Dict[str, Any]]):
    if not chunks:
        return

    BATCH = 32
    print(f"[Ingest] Upserting {len(chunks)} chunks")

    contents = [c["content"] for c in chunks]

    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i+BATCH]
        texts = contents[i:i+BATCH]

        vectors = embedder.embed_batch(texts)

        points = []
        for c, v in zip(batch, vectors):
            pid = int(uuid.uuid4().int >> 64)
            payload = {
                "section": c["section"],
                "source_file": c["source_file"],
                "chunk_id": c["chunk_id"],
                "document_title": c["document_title"],
                "council": c["council"],
                "timestamp": c["timestamp"],
                "mode": c.get("mode", "unknown")
            }
            points.append(models.PointStruct(id=pid, vector=v, payload=payload))

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=False,  # don't block on full persistence, avoids 408 timeouts
        )
        print(f"[Ingest] Batch upsert: {i+BATCH}/{len(chunks)}")

# ------------------------------------------------------------
# XML File Discovery
# ------------------------------------------------------------

def discover_xml_files(root_dir: str) -> List[str]:
    xmls = []
    for r, _, files in os.walk(root_dir):
        for f in files:
            if f.lower().endswith(".xml"):
                xmls.append(os.path.join(r, f))
    return xmls

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print(f"--- Knowledge Bob Ingestion Pipeline Start ({datetime.now().isoformat()}) ---")
    print(f"[Config] XML DIR: {PLOS_XML_DIR}")

    if not os.path.isdir(PLOS_XML_DIR):
        print("[Error] XML directory does not exist")
        return

    # Init qdrant + embedder
    client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        timeout=60.0,   # <-- added
    )
    embedder = LocalEmbedder(model_name=EMBEDDING_MODEL_NAME)

    # Make sure the global vector size matches the actual model
    global EMBEDDING_VECTOR_SIZE
    EMBEDDING_VECTOR_SIZE = embedder.vector_size

    create_qdrant_collection(client)

    xml_files = [
        os.path.join(PLOS_XML_DIR, f)
        for f in os.listdir(PLOS_XML_DIR)
        if f.endswith(".xml")
    ]

    total_files = len(xml_files)
    print(f"Found {total_files} XML articles to process.")

    START_INDEX = int(os.getenv("PLOS_START_INDEX", "1"))
    END_INDEX = int(os.getenv("PLOS_END_INDEX", str(total_files)))

    print(f"[Ingest] Processing window: {START_INDEX} → {END_INDEX}")

    if total_files == 0:
        print("[Ingest] No XML files to process, exiting.")
        return

    processed_files = 0
    all_chunks: List[Dict[str, Any]] = []

    for idx, xml_file in enumerate(xml_files, start=1):
        if idx < START_INDEX or idx > END_INDEX:
            continue

        print(f"[Ingest] === File {idx}/{total_files} === {os.path.basename(xml_file)}")
        chunks = parse_and_chunk_xml(xml_file)
        num_chunks = len(chunks)
        print(f"[Ingest] Parsed {num_chunks} chunks from {os.path.basename(xml_file)}")

        if num_chunks > 0:
            upsert_chunks(client, embedder, chunks)
            print(f"[Ingest] Finished upsert for {os.path.basename(xml_file)}")
        else:
            print(f"[Ingest] Skipping upsert for {os.path.basename(xml_file)} (no chunks)")

        all_chunks.extend(chunks)
        processed_files += 1
        print(f"[Ingest] Progress: {processed_files}/{total_files} files complete")

    print("--- Knowledge Bob Ingestion Complete ---")


if __name__ == "__main__":
    main()

