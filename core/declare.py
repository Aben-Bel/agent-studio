from dataclasses import dataclass, field
from typing import Callable, Type
from pydantic import BaseModel
from .registry import AGENTS, TOOLS, SKILLS


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
    args: Type[BaseModel]
    fn: Callable


def tool(name, description, args):
    """Declare a tool. args is a pydantic model = typed signature + JSON schema."""
    def deco(fn):
        TOOLS.register(name)(ToolDecl(name, description, args, fn))
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
