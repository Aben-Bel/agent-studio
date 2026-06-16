from dataclasses import dataclass, field
from typing import Callable, Type
from pydantic import BaseModel
from .registry import AGENTS, TOOLS, SKILLS, MCP, STAGES, EXPORTERS


# ---- AGENT ----
@dataclass
class AgentRouting:
    """Typed, structured self-description the orchestrator routes off of. Each field is
    grounded in the agent's actual system prompt + allowed tools — NOT freeform marketing.
    `what_not_to_use_for` must be specific (e.g. 'tabular only; not wafer-map images') to
    be useful. Empty fields are allowed but discouraged; the orchestrator falls back to
    `description` when routing metadata is absent."""
    when_to_use: str = ""
    how_to_use: str = ""
    what_to_use_for: str = ""
    what_not_to_use_for: str = ""
    # An agent that must run on EVERY investigation regardless of the question (e.g. an
    # intake/readiness check). The router keeps it in the selected set instead of letting
    # the LLM prune it. Declarative + generic: the orchestrator honours this flag by
    # PROPERTY, never by agent name — any agent can opt in by setting always=True.
    always: bool = False

    def as_prompt(self) -> str:
        parts = []
        if self.always:
            parts.append("ALWAYS run this (cross-cutting; do not omit)")
        if self.when_to_use:
            parts.append(f"when to use: {self.when_to_use}")
        if self.what_to_use_for:
            parts.append(f"use for: {self.what_to_use_for}")
        if self.what_not_to_use_for:
            parts.append(f"NOT for: {self.what_not_to_use_for}")
        if self.how_to_use:
            parts.append(f"how: {self.how_to_use}")
        return "; ".join(parts)


@dataclass
class AgentDecl:
    name: str
    description: str
    fn: Callable                 # fn(ctx) -> system prompt string
    tools: list = field(default_factory=list)   # tool OR skill names it may call
    routing: AgentRouting = field(default_factory=AgentRouting)   # typed routing metadata

    def routing_text(self) -> str:
        """Description enriched with routing metadata for the orchestrator's LLM router."""
        rp = self.routing.as_prompt()
        return f"{self.description} [{rp}]" if rp else self.description


def agent(name, description, tools=None, routing=None,
          when_to_use="", how_to_use="", what_to_use_for="", what_not_to_use_for="",
          always=False):
    """Declare an agent. Drop a file in agents/ with this decorator and the
    orchestrator discovers and routes to it. No shared file is edited.

    Routing metadata (typed, not prose) sharpens orchestrator routing. Pass either a
    ready `AgentRouting` via `routing=`, or the four fields directly as kwargs. Set
    `always=True` for a cross-cutting agent (e.g. intake/readiness) the router must
    never prune from a run."""
    r = routing or AgentRouting(when_to_use=when_to_use, how_to_use=how_to_use,
                                what_to_use_for=what_to_use_for,
                                what_not_to_use_for=what_not_to_use_for, always=always)
    def deco(fn):
        AGENTS.register(name)(AgentDecl(name, description, fn, tools or [], r))
        return fn
    return deco


def register_custom_agent(name, description, system, tools, routing=None):
    """Runtime agent created from the wizard (persona). Same contract, no file."""
    AGENTS.register(name)(AgentDecl(name, description, (lambda ctx, s=system: s),
                                    tools or [], routing or AgentRouting()))


# ---- TOOL ----
@dataclass
class ToolDecl:
    name: str
    description: str
    args: Type[BaseModel]                 # input schema (typed)
    fn: Callable
    returns: Type[BaseModel] = None       # optional output schema
    version: str = "2026-06-15"           # date-string version (MCP-style)
    owner: str = ""                       # who owns/maintains this tool
    tags: list = field(default_factory=list)
    limits: str = ""                      # what this tool CANNOT do (shown in UI tooltip)


def tool(name, description, args, returns=None, version="2026-06-15", owner="", tags=None,
         limits=""):
    """Declare a tool. `args` is a pydantic model = typed signature + JSON schema.
    Optionally give an output schema (`returns`), a `version`, an `owner`, and
    `limits` (a short 'what this tool CANNOT do' note surfaced in the UI tooltip)
    so the registry stays trustworthy and honest as many people add tools."""
    def deco(fn):
        TOOLS.register(name)(ToolDecl(name, description, args, fn, returns,
                                      version, owner, tags or [], limits))
        return fn
    return deco


# ---- SKILL ----
@dataclass
class SkillDecl:
    name: str
    description: str
    fn: Callable
    limits: str = ""                      # what this skill CANNOT do (UI tooltip)


def skill(name, description="", limits=""):
    """Declare a skill: a reusable multi-step routine the agent can invoke.
    `limits` is an optional 'what this CANNOT do' note shown in the UI tooltip."""
    def deco(fn):
        SKILLS.register(name)(SkillDecl(name, description, fn, limits))
        return fn
    return deco


# ---- MCP SERVER ----
@dataclass
class McpDecl:
    name: str
    description: str
    config: dict                 # {transport, command/args, url, ...} - how to reach it
    fn: Callable = None          # optional handler/factory for the connection


def mcp(name, description="", **config):
    """Declare an MCP server. Drop a file in mcp/ (any subfolder) like:

        @mcp("filesystem", "Local files", transport="stdio",
             command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/data"])
        def filesystem(): ...

    It self-registers and appears in /capabilities, same as tools/skills/agents."""
    def deco(fn=None):
        MCP.register(name)(McpDecl(name, description, config, fn))
        return fn
    return deco


# ---- EXPORTER (output generator) ----
@dataclass
class ExporterDecl:
    name: str                    # stable id, e.g. "presentation_pdf"
    label: str                   # human label, e.g. "Slide deck (PDF)"
    description: str
    extension: str               # file extension WITHOUT dot, e.g. "pdf"
    media_type: str              # MIME type for the download
    fn: Callable                 # fn(report: dict) -> bytes
    needs: list = field(default_factory=list)   # external binaries it needs (e.g. ["latexmk"])


def exporter(name, label, description="", extension="txt",
             media_type="application/octet-stream", needs=None):
    """Declare an OUTPUT generator. Symmetric to tools/skills/agents: drop a file
    in exporters/ (any subfolder) with this decorator and it appears in the
    Download menu - no shared file edited.

        @exporter("presentation_pdf", "Slide deck (PDF)",
                  extension="pdf", media_type="application/pdf", needs=["latexmk"])
        def presentation_pdf(report):
            ...                  # report = the structured investigation (see core.report)
            return pdf_bytes

    The function receives the structured report (questions, conclusions, the exact
    tools/queries used as evidence) and returns the artifact bytes."""
    def deco(fn):
        EXPORTERS.register(name)(ExporterDecl(name, label, description, extension,
                                              media_type, fn, needs or []))
        return fn
    return deco


# ---- PIPELINE STAGE ----
@dataclass
class StageDecl:
    name: str
    order: int                   # stages run low -> high
    fn: Callable                 # fn(doc: dict) -> dict
    description: str = ""


def stage(name, order=50, description=""):
    """Declare a document-processing stage. Drop a file in pipeline/ like:

        @stage("index", order=20, description="Embed chunks into the RAG store")
        def index(doc):
            ...                  # doc has {source, text, ...}; mutate + return it
            return doc

    Every uploaded document is run through all stages in `order`. Add a stage by
    dropping a file, reorder by changing the number, remove by deleting it -
    no shared file to edit, so 8 people extend the pipeline without colliding."""
    def deco(fn):
        STAGES.register(name)(StageDecl(name, order, fn, description))
        return fn
    return deco
