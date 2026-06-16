"""Human-in-the-loop tool.

When an agent calls `ask_human`, the orchestrator PAUSES the run, streams a
`needs_human` event to the frontend, and remembers exactly where it stopped. The
person's reply resumes the same session from that point - the agent then sees the
answer as this tool's result. Give an agent this tool to let it ask for input,
a missing detail, or approval mid-task.

The orchestrator intercepts this call by name, so the body never actually runs;
it exists only to declare the tool's name + argument schema.
"""
from pydantic import BaseModel
from core.declare import tool


class AskHumanArgs(BaseModel):
    question: str


@tool("ask_human",
      "Pause and ask the human a question, then continue with their answer. "
      "Use when you need input, a decision, or approval to proceed.",
      AskHumanArgs,
      limits="Asks one free-text question and waits; cannot force a reply, time out, or act without the human.")
def ask_human(question):
    # Intercepted by the orchestrator; never invoked directly.
    return question
