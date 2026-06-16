"""Investigations: run an agent (streamed), manage sessions, add context, agents."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core import orchestrator
from core.declare import register_custom_agent
from core.schemas import RunRequest, CreateAgentRequest, AddContextRequest

router = APIRouter()


@router.post("/run")
def run(req: RunRequest):
    """Run an agent. Streams orchestrator events as Server-Sent Events.

    Pass a `chat_id` to keep a stateful, resumable session: the orchestrator
    remembers the conversation, persists every step to the audit trail, can pause
    for human input (a `needs_human` event), and continues where it left off when
    you POST again with the same `chat_id`. Without a `chat_id` it runs once."""
    def gen():
        agents = req.agents or []
        if len(agents) == 1:
            # one agent -> stateful single run (supports ask_human pause/resume)
            stream = orchestrator.start_or_resume(req.chat_id or agents[0], agents[0],
                                                  req.message, req.allow_tools, req.sources, req.lang)
        elif req.agent == "team" or agents:
            stream = orchestrator.run_team(req.chat_id or "team", req.message,
                                           agents, req.allow_tools, req.sources, req.lang)
        elif req.chat_id:
            stream = orchestrator.start_or_resume(req.chat_id, req.agent, req.message, lang=req.lang)
        else:
            stream = orchestrator.run(req.agent, req.message, req.history, req.lang)
        for ev in stream:
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/continue")
def continue_run(req: RunRequest):
    """Continue a team investigation that stopped at the step limit. Streams the same
    way as /run. The user approved 'continue'; the orchestrator resumes the original
    task as a continuation, finishing only the targets left not-analyzed."""
    def gen():
        stream = orchestrator.resume_truncated(
            req.chat_id, req.agents or None, req.allow_tools, req.sources, req.lang)
        for ev in stream:
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/agents")
def create_agent(req: CreateAgentRequest):
    """Create a custom agent from a persona. Registered live and immediately
    routable and visible in /capabilities. Optional routing guidance sharpens
    routing and is shown in the agent detail."""
    from core.declare import AgentRouting
    routing = AgentRouting(when_to_use=req.when_to_use, how_to_use=req.how_to_use,
                           what_to_use_for=req.what_to_use_for,
                           what_not_to_use_for=req.what_not_to_use_for)
    register_custom_agent(req.name, req.description, req.persona, req.tools, routing)
    return {"created": req.name}


@router.get("/sessions")
def sessions_list():
    """All known sessions and where each one is (idle / awaiting_human / done)."""
    return {"sessions": orchestrator.list_sessions()}


@router.get("/sessions/{chat_id}")
def session_state(chat_id: str):
    """Restore a session: its transcript, status, and any pending question."""
    return orchestrator.session_state(chat_id)


@router.post("/sessions/{chat_id}/context")
def add_context(chat_id: str, req: AddContextRequest):
    """Add context to a session WHILE it runs. Queued on the session; the
    orchestrator picks it up on its next step - smooth catch-up, no restart."""
    return orchestrator.add_context(chat_id, req.text)
