"""Yield-analysis RCA assistant — the WIRED SKELETON.

The full reasoning agent (plan-and-execute over the tools, hypothesis ranking,
convergence) is intentionally NOT implemented yet. This declaration wires the
agent to its tools so the whole platform — streaming, audit trail, data access,
human-in-the-loop, transparency UI — works end to end and can be demonstrated.
Implement the reasoning by evolving the orchestrator / this persona later."""
from core.declare import agent


@agent(
    name="rca_assistant",
    description="Investigates semiconductor yield loss / defects and works toward a "
                "root cause (skeleton — reasoning not implemented yet).",
    tools=["correlate_params_vs_yield", "search_fmea", "query_fdc_timeseries",
           "get_wafer_map", "find_similar_cases", "search_docs", "query_data",
           "list_data_sources", "ask_human"],
)
def rca_assistant(ctx):
    return (
        "You are a semiconductor yield-analysis root-cause-analysis assistant. "
        "Given a defect or yield-loss report, investigate the likely root cause: "
        "correlate process parameters against the defect target, search FMEA/manuals "
        "for known failure modes, pull FDC traces, inspect wafer maps, and find "
        "similar historical cases. Always cite the data and documents you used. "
        "Ask the human (ask_human) when you need a missing detail or approval. "
        "NOTE: full reasoning is a work in progress — this is the wired skeleton."
    )
