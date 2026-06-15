from pydantic import BaseModel
from typing import Any, Literal, Optional


# ---- API request models (appear in Swagger) ----
class RunRequest(BaseModel):
    agent: str = "joker"
    message: str
    history: list[dict] = []


class CreateAgentRequest(BaseModel):
    name: str
    description: str
    persona: str                    # becomes the system prompt
    tools: list[str] = []           # tool/skill names this agent may call


# ---- Streamed event model (documented even though it flows over SSE) ----
class Event(BaseModel):
    type: Literal["agent_switch", "progress", "tool_call",
                  "tool_result", "final", "error"]
    data: dict[str, Any]


class Capabilities(BaseModel):
    agents: list[dict]
    tools: list[dict]
    skills: list[dict]
