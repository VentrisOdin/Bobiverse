# Memory Council (Memory Bob) v1

Endpoints:
- GET  /health
- POST /memory/event
- POST /memory/recall
- POST /memory/distill

v1 uses SQLite canonical storage for capture/recall/distill.
Qdrant integration is optional and currently only health-checks (embedding comes later).

Run (dev):
python -m uvicorn councils.memory_council.main:app --host 0.0.0.0 --port 8031 --reload
