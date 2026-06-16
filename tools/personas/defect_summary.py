"""Tool: summarize defect distribution across type, zone, and process step.

Real pandas implementation. Lets the Defect Inspection Engineer quickly see
which defect types / wafer zones / process steps account for the most defects
without writing raw SQL."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class DefectSummaryArgs(BaseModel):
    table: str = "wafer_defects"
    group_by: str = "defect_type"       # column(s) to group by, comma-separated
    count_col: str = "defect_count"     # numeric column to sum; falls back to row count
    top_n: int = 10                     # return at most this many groups


@tool(
    "summarize_defect_distribution",
    "Group a defect/inspection table by one or more columns (e.g. defect_type, "
    "wafer_zone, process_step) and return total defect counts and % share per group. "
    "Use to identify which defect types or zones dominate.",
    DefectSummaryArgs,
    owner="personas",
    tags=["defect", "inspection", "distribution"],
)
def summarize_defect_distribution(
    table="wafer_defects",
    group_by="defect_type",
    count_col="defect_count",
    top_n=10,
):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    group_cols = [c.strip() for c in group_by.split(",") if c.strip()]
    missing = [c for c in group_cols if c not in df.columns]
    if missing:
        return (f"Group column(s) not found: {', '.join(missing)}. "
                f"Available: {', '.join(df.columns)}")

    if count_col in df.columns:
        df[count_col] = pd.to_numeric(df[count_col], errors="coerce").fillna(0)
        agg = (
            df.groupby(group_cols)[count_col]
            .sum()
            .reset_index(name="total_defects")
            .sort_values("total_defects", ascending=False)
            .head(top_n)
        )
        total = agg["total_defects"].sum()
        agg["pct_share"] = (agg["total_defects"] / total * 100).round(1)
        summary_label = f"sum of {count_col}"
    else:
        # fall back to row count
        agg = (
            df.groupby(group_cols)
            .size()
            .reset_index(name="row_count")
            .sort_values("row_count", ascending=False)
            .head(top_n)
        )
        total = agg["row_count"].sum()
        agg["pct_share"] = (agg["row_count"] / total * 100).round(1)
        summary_label = "row count (defect_count column not found)"

    lines = [
        f"Defect distribution — table: {table}, grouped by: {group_by} ({summary_label})",
        agg.to_string(index=False),
    ]
    return "\n".join(lines)
