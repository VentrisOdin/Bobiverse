
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

MEMORY_BOB_PORT = int(os.getenv("MEMORY_BOB_PORT", 8031))
MEMORY_BOB_HOST = os.getenv("MEMORY_BOB_HOST", "0.0.0.0")

CANONICAL_DB_PATH = os.getenv(
	"CANONICAL_DB_PATH",
	str(Path.home() / "bobiverse/data/memory_bob/canonical.db")
)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

MEMORY_COLLECTION_EVENTS = os.getenv("MEMORY_COLLECTION_EVENTS", "memory_events")
MEMORY_COLLECTION_LESSONS = os.getenv("MEMORY_COLLECTION_LESSONS", "memory_lessons")

MEMORY_RECALL_LIMIT_DEFAULT = int(os.getenv("MEMORY_RECALL_LIMIT_DEFAULT", 5))
MEMORY_QDRANT_TIMEOUT = int(os.getenv("MEMORY_QDRANT_TIMEOUT", 5))
