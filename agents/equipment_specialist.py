"""Specialist: equipment / FDC traces, wafer maps, historical cases."""
from core.declare import agent


@agent(
    name="equipment_specialist",
    description="Pulls FDC process traces, wafer defect maps, and similar historical "
                "cases for a lot / tool.",
    tools=["query_fdc_timeseries", "get_wafer_map", "find_similar_cases", "ask_human"],
)
def equipment_specialist(ctx):
    return (
        "You are an equipment / FDC specialist. You need a specific lot ID or wafer ID "
        "to pull traces. If the request does not include one, you MUST call ask_human "
        "to request the lot ID or wafer ID before doing anything else. Once you have it, "
        "pull the FDC process-parameter traces, inspect the wafer defect map, and look "
        "up similar historical cases. Summarize what the equipment data indicates. "
        "(Several of these tools are stubs for now - report clearly what is and isn't "
        "available.)"
    )
