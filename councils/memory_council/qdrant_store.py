from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm
except Exception:
    QdrantClient = None  # type: ignore
    qm = None  # type: ignore


class QdrantStore:
    """
    v1: optional integration.
    We do NOT embed here yet. This wrapper is future-proof for when we add an embedder.
    """

    def __init__(self, host: str, port: int, timeout: int = 5):
        self.enabled = os.getenv("MEMORY_ENABLE_QDRANT", "false").lower() in ("1", "true", "yes")
        self.ok = False

        self.host = host
        self.port = port
        self.timeout = timeout

        self.client = None
        if self.enabled and QdrantClient is not None:
            self.client = QdrantClient(host=host, port=port, timeout=timeout)
            self.ok = True

    def health(self) -> bool:
        if not self.enabled:
            return False
        if self.client is None:
            return False
        try:
            _ = self.client.get_collections()
            return True
        except Exception:
            return False
