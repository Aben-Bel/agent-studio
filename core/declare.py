from dataclasses import dataclass, field
from typing import Callable, Type
from pydantic import BaseModel
from .registry import AGENTS, TOOLS, SKILLS, MCP, STAGES


# ---- AGENT ----
@dataclass
class AgentDecl:
    name: str
    description: str
    fn: Callable                 # fn(ctx) -> system prompt string
    tools: list = field(default_factory=list)   # tool OR skill names it may call


def agent(name, description, tools=None):
    """Declare an agent. Drop a file in agents/ with this decorator and the
    orchestrator discovers and routes to it. No shared file is edited."""
    def deco(fn):
        AGENTS.register(name)(AgentDecl(name, description, fn, tools or []))
        return fn
    return deco


def register_custom_agent(name, description, system, tools):
    """Runtime agent created from the wizard (persona). Same contract, no file."""
    AGENTS.register(name)(AgentDecl(name, description, (lambda ctx, s=system: s), tools or []))


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


def tool(name, description, args, returns=None, version="2026-06-15", owner="", tags=None):
    """Declare a tool. `args` is a pydantic model = typed signature + JSON schema.
    Optionally give an output schema (`returns`), a `version`, and an `owner` so the
    registry stays trustworthy as many people add tools."""
    def deco(fn):
        TOOLS.register(name)(ToolDecl(name, description, args, fn, returns,
                                      version, owner, tags or []))
        return fn
    return deco


# ---- SKILL ----
@dataclass
class SkillDecl:
    name: str
    description: str
    fn: Callable


def skill(name, description=""):
    """Declare a skill: a reusable multi-step routine the agent can invoke."""
    def deco(fn):
        SKILLS.register(name)(SkillDecl(name, description, fn))
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
