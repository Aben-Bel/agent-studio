"""Specialist: equipment / FDC traces, wafer maps, historical cases."""
from core.declare import agent


@agent(
    name="equipment_specialist",
    description="Pulls FDC process traces, wafer defect maps, and similar historical "
                "cases for a lot / tool.",
    tools=["query_fdc_timeseries", "get_wafer_map", "find_similar_cases"],
)
def equipment_specialist(ctx):
    return (
        "You are an equipment / FDC specialist. For a lot, tool, or wafer, pull the "
        "FDC process-parameter traces, inspect the wafer defect map, and look up "
        "similar historical cases and their confirmed root cause. Summarize what the "
        "equipment data indicates. (Several of these tools are stubs for now — report "
        "clearly what is and isn't available.)"
    )
