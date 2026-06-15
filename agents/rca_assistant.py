"""Yield-analysis RCA supervisor - coordinates specialist agents.

The orchestrator recruits multiple agents: this supervisor delegates sub-tasks to
data_analyst, manuals_expert, and equipment_specialist via `consult_agent`, then
synthesizes their findings into a root-cause conclusion. The full autonomous
reasoning is still evolving - this is the wired multi-agent skeleton, and every
recruited agent's steps stream into the same transparent trace."""
from core.declare import agent


@agent(
    name="rca_assistant",
    description="Supervises a yield-loss investigation, recruiting specialist agents "
                "and synthesizing a root cause.",
    tools=["consult_agent", "correlate_params_vs_yield", "search_fmea",
           "search_docs", "query_data", "list_data_sources", "ask_human"],
)
def rca_assistant(ctx):
    return (
        "You are the lead investigator for a semiconductor yield-loss root-cause "
        "analysis. Coordinate a team of specialists and synthesize their findings.\n\n"
        "Recruit specialists with consult_agent(agent, task):\n"
        "  - data_analyst - correlate process parameters with the defect target, query data\n"
        "  - manuals_expert - find known failure modes in manuals / FMEA\n"
        "  - equipment_specialist - FDC traces, wafer maps, similar historical cases\n\n"
        "Typical flow: ask data_analyst which parameters drive the defect, ask "
        "manuals_expert what those parameters' failure modes are, optionally ask "
        "equipment_specialist for traces, then give a concise root-cause conclusion "
        "that cites the evidence. Use ask_human if a key detail is missing. Keep it "
        "focused - delegate rather than calling every tool yourself."
    )
