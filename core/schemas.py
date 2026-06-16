from pydantic import BaseModel
from typing import Any, Literal, Optional


# ---- API request models (appear in Swagger) ----
class RunRequest(BaseModel):
    agent: str = "team"             # "team" = run agents in parallel; or a single agent name
    message: str
    history: list[dict] = []
    chat_id: Optional[str] = None   # set it to keep a stateful, resumable session
    agents: Optional[list[str]] = None      # team mode: which agents to run in parallel
    allow_tools: Optional[list[str]] = None  # restrict which tools/skills agents may use
    sources: Optional[list[str]] = None      # restrict which data sources to use
    lang: str = "en"                # UI language ("en"/"de"); the OTHER language is
                                    # auto-translated so each message carries {en, de}


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
    type: Literal["agent_switch", "progress", "thinking", "tool_call", "tool_result",
                  "needs_human", "context_added", "user_message", "suggestions",
                  "artifact", "final", "error"]
    data: dict[str, Any]


class AddContextRequest(BaseModel):
    text: str                       # extra context to feed an in-progress chat


class ExportRequest(BaseModel):
    chat_id: str                    # which investigation to turn into an artifact
    format: str                     # exporter name, e.g. "report_md" / "presentation_pdf"
    title: Optional[str] = None     # optional report title override
    lang: str = "en"                # language to author the document in ("en"/"de")


class Capabilities(BaseModel):
    agents: list[dict]
    tools: list[dict]
    skills: list[dict]
    mcp: list[dict] = []
    stages: list[dict] = []     # document-processing pipeline steps
