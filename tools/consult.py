"""Multi-agent recruiting tool.

When a (supervisor) agent calls `consult_agent`, the orchestrator RECRUITS the
named specialist agent, runs it on the given task as a nested investigation,
streams its every step (so the trace shows which agent is working), and returns
its conclusion back to the supervisor. This is how one investigation pulls in
multiple agents. The orchestrator intercepts this by name - the body never runs.
"""
from pydantic import BaseModel
from core.declare import tool


class ConsultArgs(BaseModel):
    agent: str           # which specialist agent to recruit
    task: str            # what to ask it to do


@tool("consult_agent",
      "Recruit another specialist agent to handle a sub-task and return its findings. "
      "Persona specialists: yield_statistician, metrology_analyst, "
      "defect_profiler, rca_engineer. "
      "Supporting: data_analyst, manuals_expert, equipment_specialist.",
      ConsultArgs, owner="orchestration", tags=["multi-agent"],
      limits="Recruits only the registered specialist agents; cannot invoke external services or arbitrary tools.")
def consult_agent(agent, task):
    return f"(recruiting {agent})"   # intercepted by the orchestrator
