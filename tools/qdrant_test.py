# tools/qdrant_test.py

from qdrant_helper import ensure_collection, upsert_text_chunks, search_similar
from qdrant_helper import get_client, QDRANT_COLLECTION


def main() -> None:
    print("Ensuring collection exists...")
    ensure_collection()

    client = get_client()
    print("Current collections:")
    print(client.get_collections())

    # Upsert a tiny test doc
    chunks = [
        {
            "id": 1,
            "text": "Knowledge Bob is the central RAG-powered council that answers factual questions for the Bobiverse.",
            "metadata": {"source": "test", "council": "knowledge"},
        }
    ]

    print("Upserting test chunk...")
    upsert_text_chunks(chunks)

    print("Searching for 'What is Knowledge Bob?'...")
    results = search_similar("What is Knowledge Bob?", limit=3)
    for r in results:
        print(f"Score: {r['score']:.3f}")
        print(f"Text: {r['payload']['text'][:200]}...")
        print("-" * 40)


if __name__ == "__main__":
    main()
