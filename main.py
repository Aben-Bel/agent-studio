import os, json, tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from core.config import cfg
from core.discovery import discover
from core.declare import register_custom_agent
from core import orchestrator
from core.schemas import (RunRequest, CreateAgentRequest, ConnectDbRequest,
                          Capabilities, Event)
from core.util import log
from connectors import datastore
from connectors.ingest import ingest
from connectors.s3 import s3
from pydantic import BaseModel

discover()   # auto-register everything in agents/ tools/ skills/ connectors/

# Connect a database given via env up front; runtime URLs come in via /connect-db.
if cfg.database_url:
    try:
        info = datastore.connect_db(cfg.database_url, "default")
        log.info("connected env database as '%s' (%s)", info["name"], info["dialect"])
    except Exception as e:
        log.warning("DATABASE_URL could not be connected: %s", e)

app = FastAPI(title="Joke Platform API",
              description="Auto-discovered agents, tools, skills. "
                          "Frontend builds against this OpenAPI spec.",
              version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/capabilities", response_model=Capabilities)
def capabilities():
    """Everything the system can do right now, generated from the registries.
    New agents/tools/skills appear here with no code change."""
    return orchestrator.capabilities()


@app.post("/upload")
async def upload(files: list[UploadFile] = File(default=None),
                 file: UploadFile = File(default=None)):
    """Ingest one or many files in a single request. CSVs each become their own
    SQL table; PDF/TXT/MD become searchable documents. Accepts the multi-file
    field `files` (preferred) and a single `file` for backward compatibility.
    Returns {"results": [{name, kind, ...}, ...]}."""
    incoming = list(files or [])
    if file is not None:
        incoming.append(file)

    results = []
    for uf in incoming:
        suffix = os.path.splitext(uf.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(await uf.read())
            path = f.name
        try:
            results.append({"name": uf.filename, **ingest(path, uf.filename)})
        except Exception as e:
            results.append({"name": uf.filename, "kind": "error", "reason": str(e)})
        finally:
            os.unlink(path)
    return {"results": results}


class PresignRequest(BaseModel):
    filename: str
    content_type: str | None = None


class S3Ref(BaseModel):
    # The key (or full s3:// / https URL) returned by /uploads/presign.
    key: str


@app.post("/uploads/presign")
def presign_upload(req: PresignRequest):
    """Hand the browser a presigned URL so it can PUT a file straight to S3
    (bytes never pass through the backend). The browser then sends `key` back
    — e.g. to /ingest-s3 — for the backend to pick up."""
    return s3.presign_put(req.filename, req.content_type)


@app.post("/ingest-s3")
def ingest_s3(ref: S3Ref):
    """Pick up a previously-uploaded S3 object by key/link, download it, and run
    it through the same ingest pipeline as a direct upload."""
    bucket, key = s3.parse(ref.key)
    try:
        path = s3.download_to_tmp(ref.key)
    except Exception as e:
        return {"name": os.path.basename(key), "kind": "error",
                "reason": f"could not fetch s3 object: {e}"}
    try:
        return {"name": os.path.basename(key), "key": key, **ingest(path, key)}
    except Exception as e:
        return {"name": os.path.basename(key), "kind": "error", "reason": str(e)}
    finally:
        os.unlink(path)


@app.post("/connect-db")
def connect_db(req: ConnectDbRequest):
    """Connect an external database by URL (e.g. a Postgres link). It is
    validated, introspected, and registered as a queryable data source.
    Call it repeatedly to connect several databases."""
    try:
        return {"connected": True, **datastore.connect_db(req.url, req.name)}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.get("/sources")
def sources():
    """List every connected data source and the tables inside it: the local
    CSV store plus any databases added via /connect-db or DATABASE_URL."""
    return {"sources": datastore.list_sources()}


@app.post("/agents")
def create_agent(req: CreateAgentRequest):
    """Create a custom agent from a persona (the wizard uses this). It is
    registered live and immediately routable and visible in /capabilities."""
    register_custom_agent(req.name, req.description, req.persona, req.tools)
    return {"created": req.name}


@app.post("/run")
def run(req: RunRequest):
    """Run an agent. Streams orchestrator events as Server-Sent Events.

    Pass a `chat_id` to keep a stateful, resumable session: the orchestrator
    remembers the conversation, can pause for human input (a `needs_human`
    event), and continues where it left off when you POST again with the same
    `chat_id`. Without a `chat_id` it runs once, statelessly (legacy)."""
    def gen():
        if req.chat_id:
            stream = orchestrator.start_or_resume(req.chat_id, req.agent, req.message)
        else:
            stream = orchestrator.run(req.agent, req.message, req.history)
        for ev in stream:
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/sessions")
def sessions_list():
    """All known chat sessions and where each one is (idle / awaiting_human / done)."""
    return {"sessions": orchestrator.list_sessions()}


@app.get("/sessions/{chat_id}")
def session_state(chat_id: str):
    """Restore a chat: its transcript, status, and any pending question it
    paused on. Lets the frontend reopen a session exactly where it stopped."""
    return orchestrator.session_state(chat_id)


# Surfaces the Event schema in OpenAPI so the UI team sees the streamed shape.
@app.get("/event-schema", response_model=Event)
def event_schema():
    return {"type": "progress", "data": {"message": "example"}}
