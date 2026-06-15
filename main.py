import os, json, tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from core.discovery import discover
from core.declare import register_custom_agent
from core import orchestrator
from core.schemas import RunRequest, CreateAgentRequest, Capabilities, Event
from connectors.ingest import ingest

discover()   # auto-register everything in agents/ tools/ skills/ connectors/

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
async def upload(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(await file.read())
        path = f.name
    return ingest(path, file.filename)


@app.post("/agents")
def create_agent(req: CreateAgentRequest):
    """Create a custom agent from a persona (the wizard uses this). It is
    registered live and immediately routable and visible in /capabilities."""
    register_custom_agent(req.name, req.description, req.persona, req.tools)
    return {"created": req.name}


@app.post("/run")
def run(req: RunRequest):
    """Run an agent. Streams orchestrator events as Server-Sent Events.
    Event shape is documented by the Event model in this spec."""
    def gen():
        for ev in orchestrator.run(req.agent, req.message, req.history):
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


# Surfaces the Event schema in OpenAPI so the UI team sees the streamed shape.
@app.get("/event-schema", response_model=Event)
def event_schema():
    return {"type": "progress", "data": {"message": "example"}}
