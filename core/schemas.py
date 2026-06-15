from pydantic import BaseModel
from typing import Any, Literal, Optional


# ---- API request models (appear in Swagger) ----
class RunRequest(BaseModel):
    agent: str = "joker"
    message: str
    history: list[dict] = []
    chat_id: Optional[str] = None   # set it to keep a stateful, resumable session


class CreateAgentRequest(BaseModel):
    name: str
    description: str
    persona: str                    # becomes the system prompt
    tools: list[str] = []           # tool/skill names this agent may call


class ConnectDbRequest(BaseModel):
    url: str                        # e.g. postgresql://user:pass@host:5432/dbname
    name: Optional[str] = None      # optional label; defaults to the db name


# ---- Streamed event model (documented even though it flows over SSE) ----
class Event(BaseModel):
    type: Literal["agent_switch", "progress", "tool_call", "tool_result",
                  "needs_human", "context_added", "final", "error"]
    data: dict[str, Any]


class AddContextRequest(BaseModel):
    text: str                       # extra context to feed an in-progress chat


class Capabilities(BaseModel):
    agents: list[dict]
    tools: list[dict]
    skills: list[dict]
    mcp: list[dict] = []
    stages: list[dict] = []     # document-processing pipeline steps
