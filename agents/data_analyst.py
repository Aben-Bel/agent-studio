"""Specialist: statistical analysis of defect / process data."""
from core.declare import agent


@agent(
    name="data_analyst",
    description="Tests which process step/parameter is associated with the defect/yield "
                "outcome and runs read-only SQL on the defect tables.",
    tools=["correlate_params_vs_yield", "query_data", "list_data_sources"],
    when_to_use="a data-driven question about which step/parameter is associated with defects, "
                "or any focused SQL lookup against a loaded defect table",
    how_to_use="give it the table and (optionally) the grouping and binary outcome columns; "
               "it returns a tested finding or an explicit no-association/insufficient-data result",
    what_to_use_for="per-group association testing (effect size + FDR-adjusted p) and ad-hoc "
                    "SELECT queries on tabular defect data",
    what_not_to_use_for="tabular SQL data only — NOT FMEA/manual text search, NOT wafer-map "
                        "images, NOT FDC time-series; does not assert causation, only association",
)
def data_analyst(ctx):
    return (
        "You are a data analyst for semiconductor yield. Quantify which process "
        "parameters drive defects: rank parameters by correlation with the defect "
        "target and run focused SQL queries on the defect tables. Report numbers and "
        "cite the table/columns you used. Be concise."
    )
