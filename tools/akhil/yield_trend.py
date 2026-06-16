"""Tool: track defect rate over wafer sequence to detect drift vs excursion.

Splits wafers into equal-sized windows and computes the defect rate per
window. A gradually rising rate = process drift (slow contamination, tool
wear). A sudden spike = excursion (equipment failure, bad lot). The two
patterns need completely different fixes."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class YieldTrendArgs(BaseModel):
    table: str = "wafer_defects"
    wafer_col: str = "wafer_id"
    defect_col: str = "defect_label"
    windows: int = 5


@tool(
    "yield_trend",
    "Track defect rate over the wafer sequence to detect yield drift (gradual "
    "worsening) vs excursion (sudden spike). Splits wafers into time windows and "
    "reports defect rate per window. Drift = process degradation; spike = equipment "
    "event. Use to answer 'is yield getting worse over time?'",
    YieldTrendArgs,
    owner="akhil",
    tags=["yield", "trend", "drift", "excursion"],
    limits="Flags drift/excursion patterns as observations only; does not establish a cause and needs a numeric wafer-order column.",
)
def yield_trend(
    table="wafer_defects",
    wafer_col="wafer_id",
    defect_col="defect_label",
    windows=5,
):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)

    missing = [c for c in [wafer_col, defect_col] if c not in df.columns]
    if missing:
        return (f"Column(s) not found: {', '.join(missing)}. "
                f"Available: {', '.join(df.columns)}")

    df[wafer_col] = pd.to_numeric(df[wafer_col], errors="coerce")
    df[defect_col] = pd.to_numeric(df[defect_col], errors="coerce").fillna(0)
    df = df.dropna(subset=[wafer_col]).sort_values(wafer_col)

    df["window"] = pd.cut(df[wafer_col], bins=windows, labels=[
        f"W{i+1}" for i in range(windows)
    ])

    trend = (
        df.groupby("window", observed=True)
        .agg(
            wafer_count=(wafer_col, "count"),
            defect_count=(defect_col, "sum"),
        )
        .reset_index()
    )
    trend["defect_rate_%"] = (trend["defect_count"] / trend["wafer_count"] * 100).round(2)

    rates = trend["defect_rate_%"].tolist()
    first, last = rates[0], rates[-1]
    peak = trend.loc[trend["defect_rate_%"].idxmax()]

    # Descriptive pattern flags only. We do NOT assert a cause here: a rising rate or
    # a spike is an OBSERVATION to investigate, not an established root cause. Naming a
    # "likely cause" from a rate threshold alone is exactly the unsupported causal claim
    # the platform must not make.
    if last > first + 5:
        pattern = ("DRIFT — defect rate rises across the wafer sequence "
                   f"({first:.2f}% → {last:.2f}%). Observation only; investigate candidates "
                   "(e.g. tool wear, contamination buildup) before asserting a cause.")
    elif peak["defect_rate_%"] > (sum(rates) / len(rates)) * 1.5:
        pattern = (f"EXCURSION — spike in window {peak['window']} ({peak['defect_rate_%']}%). "
                   "Observation only; investigate candidates (e.g. equipment event, material "
                   "lot, process upset) before asserting a cause.")
    else:
        pattern = "STABLE — no marked drift or excursion across the wafer sequence."

    lines = [
        f"Yield trend analysis — table: {table}, {windows} windows over {wafer_col}",
        "",
        trend.to_string(index=False),
        "",
        f"Pattern: {pattern}",
    ]
    return "\n".join(lines)
