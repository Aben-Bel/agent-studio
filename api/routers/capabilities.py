"""Platform introspection: what the system can do, and the audit trail."""
from fastapi import APIRouter

from core import orchestrator, runs
from core.schemas import Capabilities, Event

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/capabilities", response_model=Capabilities)
def capabilities():
    """Everything the system can do right now, generated from the registries:
    agents, tools (with version/owner), skills, MCP servers, and pipeline stages.
    New capabilities appear here with no code change."""
    return orchestrator.capabilities()


@router.get("/runs")
def list_runs():
    """The investigation audit trail: every run, its agent, status, and step count."""
    return {"runs": runs.list_runs()}


@router.get("/runs/{chat_id}")
def get_run(chat_id: str):
    """Full, replayable trace of one investigation - every step persisted."""
    return runs.get_run(chat_id)


# Surfaces the Event schema in OpenAPI so the UI team sees the streamed shape.
@router.get("/event-schema", response_model=Event)
def event_schema():
    return {"type": "progress", "data": {"message": "example"}}
