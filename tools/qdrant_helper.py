# tools/qdrant_helper.py

from typing import Optional, List, Dict, Any
import os
import requests
from urllib.parse import urljoin

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

# Config – you can move these into your .env later
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")  # optional
QDRANT_COLLECTION = os.getenv("QDRANT_KNOWLEDGE_COLLECTION", "knowledge_bob")
EMBED_MODEL_NAME = os.getenv("KNOWLEDGE_EMBED_MODEL", "all-MiniLM-L6-v2")

_client: Optional[QdrantClient] = None
_embedder: Optional[SentenceTransformer] = None
_vector_size: Optional[int] = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _client


def get_embedder() -> SentenceTransformer:
    global _embedder, _vector_size
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
        test_vec = _embedder.encode("dimension probe", convert_to_numpy=True)
        _vector_size = int(test_vec.shape[0])
    return _embedder


def ensure_collection() -> None:
    """
    Create / recreate the knowledge_bob collection with the correct vector size.
    """
    client = get_client()
    embedder = get_embedder()

    test_vec = embedder.encode("dimension probe", convert_to_numpy=True)
    size = int(test_vec.shape[0])

    client.recreate_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(
            size=size,
            distance=Distance.COSINE,
        ),
    )


def embed_texts(texts: List[str]) -> List[List[float]]:
    embedder = get_embedder()
    vecs = embedder.encode(texts, convert_to_numpy=True)
    return vecs.tolist()


def upsert_text_chunks(chunks: List[Dict[str, Any]]) -> None:
    """
    chunks: list of dicts with keys:
      - "id": int or str
      - "text": str
      - "metadata": dict (optional)
    """
    client = get_client()
    vectors = embed_texts([c["text"] for c in chunks])

    points = []
    for vec, chunk in zip(vectors, chunks):
        points.append(
            PointStruct(
                id=chunk["id"],
                vector=vec,
                payload={
                    "text": chunk["text"],
                    **(chunk.get("metadata") or {}),
                },
            )
        )

    client.upsert(collection_name=QDRANT_COLLECTION, points=points)


def search_similar(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search similar points in the current collection using Qdrant's HTTP API.
    This avoids any qdrant_client version differences around .search / .search_points.
    """
    embedder = get_embedder()
    query_vec = embedder.encode(query, convert_to_numpy=True).tolist()

    # Ensure base URL has no trailing slash
    base = QDRANT_URL.rstrip("/")
    url = f"{base}/collections/{QDRANT_COLLECTION}/points/search"

    payload = {
        "vector": query_vec,
        "limit": limit,
        "with_payload": True,
    }

    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("result", [])
    out: List[Dict[str, Any]] = []
    for point in results:
        out.append(
            {
                "id": point.get("id"),
                "score": point.get("score"),
                "payload": point.get("payload", {}),
            }
        )
    return out
