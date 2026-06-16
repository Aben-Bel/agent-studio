"""Specialist: equipment / FDC traces, wafer maps, historical cases."""
from core.declare import agent


@agent(
    name="equipment_specialist",
    description="Pulls FDC process traces, wafer defect maps, and similar historical "
                "cases for a lot / tool.",
    tools=["query_fdc_timeseries", "get_wafer_map", "find_similar_cases"],
    when_to_use="a specific lot ID or wafer ID is known and you need its FDC trace, spatial "
                "defect map, or matching historical cases",
    how_to_use="provide the lot/wafer identifier; if it is absent from the data the agent "
               "reports a DATA GAP rather than asking the user",
    what_to_use_for="equipment-level confirmation: FDC time-series, wafer defect maps, "
                    "historical case lookup",
    what_not_to_use_for="NOT for tabular statistics or association testing, NOT for FMEA/manual "
                        "text; its tools are STUBS — cannot produce real traces/maps yet",
)
def equipment_specialist(ctx):
    return (
        "You are an equipment / FDC specialist. Answer the question that was actually "
        "asked using the data and tools available. The FDC/wafer-map tools need a lot ID "
        "or wafer ID; if that identifier is not present in the available data, do NOT ask "
        "the user for it - report it as a DATA GAP in your findings (name the exact "
        "missing column/identifier and which tool needs it). Never redirect a schema gap "
        "back to the user as a question. (Several of these tools are stubs for now - "
        "report clearly what is and isn't available.)"
    )
