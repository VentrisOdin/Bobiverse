# Thin shim so systemd / uvicorn can import the app using
# "councils.knowledge_council.kncouncil_service:app"

from .knowledge_council_service import app
