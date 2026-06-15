"""Specialist: statistical analysis of defect / process data."""
from core.declare import agent


@agent(
    name="data_analyst",
    description="Correlates process parameters against the defect/yield target and "
                "queries the defect datasets.",
    tools=["correlate_params_vs_yield", "query_data", "list_data_sources"],
)
def data_analyst(ctx):
    return (
        "You are a data analyst for semiconductor yield. Quantify which process "
        "parameters drive defects: rank parameters by correlation with the defect "
        "target and run focused SQL queries on the defect tables. Report numbers and "
        "cite the table/columns you used. Be concise."
    )
