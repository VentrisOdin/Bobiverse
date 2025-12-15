## Teacher Council (Internet Gateway)

**Purpose:**  
Teacher Council is the only Bobiverse service permitted to access the public internet.  
It retrieves information from trusted external sources, enforces domain allowlists,
returns citations and summaries, and produces knowledge chunks suitable for ingestion
into Knowledge Bob’s vector brain.

**Service name:** `teacher_council.service`  
**Default port:** `8013`  
**Health endpoint:** `GET /health`  
**Research endpoint:** `POST /teacher_council/research`

---

### Install dependencies (once)

```bash
cd ~/bobiverse
source .venv/bin/activate
pip install fastapi uvicorn requests
pip install beautifulsoup4
