# Agent Studio

Build a chat assistant on **your own data**, with an auto-discovered agent/tool/skill/MCP
architecture that 8+ people can extend in parallel with zero merge conflicts.

- **Bring your data:** upload many CSVs (each becomes its own SQL table), many PDFs/notes
  (chunked into searchable knowledge), and connect live database URLs (Postgres/MySQL/…).
- **Two modes:** *Simple* (add data → write a one-line persona → chat) for non-technical
  users, and a *God mode* toggle that exposes everything — data sources, agent/workflow
  building, and the full capability catalog.
- **Stateful, human-in-the-loop orchestrator:** a person starts a chat; every step streams
  live; the agent can pause to ask the human (`ask_human`) and the session remembers exactly
  where it stopped, then continues on their reply.
- Runs offline with a mock model; flip `MOCK_LLM=0` (+ AWS creds) to use Bedrock.

## Run

Docker (what we actually use):
```bash
docker compose up -d --build
# frontend:  http://localhost:8095
# backend:   http://localhost:8001/docs   (Swagger — try every endpoint)
docker compose exec backend python -m scripts.seed   # load the sample jokes dataset
```

Local dev (no Docker):
```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt
python -m scripts.seed
uvicorn main:app --reload --port 8000          # backend
cd frontend && npm install && npm run dev      # frontend (proxies /api to the backend)
```

`.env` holds AWS creds + `MOCK_LLM`/`MODEL_ID`/`AWS_REGION` (gitignored). With `MOCK_LLM=1`
the whole demo runs offline. `DATABASE_URL` (optional) connects a database at startup.

## How 8 people extend it, with no collisions
Everything is a self-declaring file, **auto-discovered at startup, including subfolders** —
so each person works in their own folder (`tools/<you>/...`) and never edits a shared file.

Add a tool → `tools/anything.py` (or `tools/you/anything.py`):
```python
from pydantic import BaseModel
from core.declare import tool
class Args(BaseModel):
    topic: str
@tool("dad_joke", "Return a dad joke about a topic.", Args)
def dad_joke(topic): ...
```
Add a skill → `skills/anything.py` with `@skill`. Add an agent → `agents/anything.py` with
`@agent`. Add an MCP server → `mcp/anything.py`:
```python
from core.declare import mcp
@mcp("filesystem", "Local files via the reference server.",
     transport="stdio", command="npx",
     args=["-y", "@modelcontextprotocol/server-filesystem", "./data"])
def filesystem(): ...
```
Drop the file, restart, and it appears in `/capabilities`, the orchestrator routes to it,
and the frontend shows it. Nobody edits anyone else's file.

## API contract (what the UI builds against)
- `GET  /capabilities` — auto-discovered `agents`, `tools`, `skills`, `mcp`
- `POST /upload` — one or many files (`files`); CSV → SQL table, PDF/TXT/MD → searchable docs
- `POST /connect-db` — connect a database by URL; validated + introspected + registered
- `GET  /sources` — every connected source (local CSV store + connected DBs) and its tables
- `POST /agents` — create a custom agent from a persona (+ which tools/skills it may use)
- `POST /run` — run an agent; streams orchestrator events (SSE). Pass `chat_id` for a
  **stateful, resumable** session (memory + human-in-the-loop)
- `GET  /sessions` and `GET /sessions/{chat_id}` — list / restore a chat (transcript, status,
  any pending question it paused on)
- `POST /uploads/presign` + `POST /ingest-s3` — direct browser→S3 upload, then ingest
- `GET  /health`, `GET /docs`, `GET /openapi.json`

Streamed event types: `agent_switch`, `progress`, `tool_call`, `tool_result`, **`needs_human`**,
`final`, `error` (see the `Event` model in the spec).

## Data + model notes
- `connectors/datastore.py` — multi-source SQL via SQLAlchemy. "local" is a bundled SQLite
  file for uploaded CSVs; any connected URL is just a different engine behind the same API.
- `connectors/memory.py` — offline keyword RAG. Swap this one module for a vector store.
- `connectors/ingest.py` — routes uploads (CSV→table, PDF/TXT/MD→RAG).
- `core/model.py` — offline mock that emulates tool use; `MOCK_LLM=0` calls Bedrock `converse`.
- `core/orchestrator.py` — stateful, human-in-the-loop sessions (in-memory; swap for Redis/SQL).

## Layout
```
core/        contract: discovery (recursive), registry, declare, orchestrator, model, schemas
agents/      one self-declaring file per agent       (subfolders OK)
tools/       one self-declaring file per tool         (subfolders OK)
skills/      one self-declaring file per skill        (subfolders OK)
mcp/         one self-declaring file per MCP server   (subfolders OK)
connectors/  datastore (SQL), memory (RAG), ingest (routing), s3 (direct upload)
frontend/    React + Vite — Simple flow + God mode
data/        sample dataset; scripts/seed.py loads it
```
