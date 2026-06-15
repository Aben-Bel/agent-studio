# Agent Studio

Build a chat assistant on **your own data**, with an auto-discovered agent/tool/skill/MCP
architecture a whole team can extend in parallel — no shared files, no merge conflicts.

- **Bring your data:** upload CSVs (each → its own SQL table) and PDFs/notes (chunked into
  searchable knowledge), or connect a live database URL (Postgres/MySQL/…).
- **Two modes:** *Simple* (add data → one-line persona → chat) and a *God mode* toggle that
  exposes data sources, agent building, and the full capability catalog.
- **Stateful, human-in-the-loop:** every step streams live; the agent can pause to ask the
  human (`ask_human`) and resume the session exactly where it stopped.
- **Offline by default** (mock model); set `MOCK_LLM=0` + AWS creds to use Bedrock.

## Run

Docker (recommended):
```bash
docker compose up -d --build
docker compose exec backend python -m scripts.seed   # load the sample dataset
# frontend  http://localhost:8095
# API docs  http://localhost:8001/docs   (Swagger — try every endpoint)
```

Local dev (no Docker):
```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt && python -m scripts.seed
uvicorn main:app --reload --port 8000          # backend
cd frontend && npm install && npm run dev      # frontend → proxies /api to :8000
```

Deploy to AWS (Terraform → EC2 + docker compose): `cd infra && terraform apply` —
see [infra/README.md](infra/README.md).

`.env` (gitignored) holds AWS creds + `MOCK_LLM` / `MODEL_ID` / `AWS_REGION` / `S3_BUCKET`;
optional `DATABASE_URL` connects a database at startup. With `MOCK_LLM=1` it runs fully offline.

## Extend it in parallel

Every capability is a self-declaring file, **auto-discovered at startup (subfolders included)**,
so each person works in their own folder (`tools/<you>/…`) and never edits a shared file.

```python
# tools/you/dad_joke.py
from pydantic import BaseModel
from core.declare import tool
class Args(BaseModel):
    topic: str
@tool("dad_joke", "Return a dad joke about a topic.", Args)
def dad_joke(topic): ...
```

Same pattern with `@skill` (`skills/…`), `@agent` (`agents/…`), and `@mcp` (`mcp/…`). Drop the
file, restart, and it appears in `/capabilities`, the orchestrator routes to it, and the UI shows it.

## API

- `GET  /capabilities` — auto-discovered `agents`, `tools`, `skills`, `mcp`
- `POST /upload` — one or many files; CSV → SQL table, PDF/TXT/MD → searchable docs
- `POST /uploads/presign` + `POST /ingest-s3` — direct browser→S3 upload, then ingest
- `POST /connect-db` · `GET /sources` — connect / list databases and their tables
- `POST /agents` — create a custom agent from a persona
- `POST /run` — run an agent; streams SSE events. Pass `chat_id` for a stateful, resumable session
- `GET  /sessions` · `GET /sessions/{chat_id}` — list / restore a chat (transcript, status, pending question)
- `GET  /health` · `/docs` · `/openapi.json`

Streamed events: `agent_switch`, `progress`, `tool_call`, `tool_result`, `needs_human`, `final`, `error`.

## Layout

```
core/        discovery (recursive), registry, declare, orchestrator, model, schemas
agents/ tools/ skills/ mcp/   one self-declaring file each (subfolders OK)
connectors/  datastore (SQL via SQLAlchemy), memory (RAG), ingest (routing), s3 (direct upload)
frontend/    React + Vite — Simple flow + God mode
infra/       Terraform — one-command EC2 deploy
data/        sample dataset (scripts/seed.py loads it)
```
