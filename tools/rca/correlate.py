"""RCA tool: correlate process parameters against the defect/yield target.

This is a REAL, working tool (the deterministic 'R/Excel script' the engineer
writes by hand today). It ranks every numeric process parameter by its absolute
correlation with the defect target over a loaded table - e.g. the seeded
`wafer_defects` table. Drop more analysis tools beside this one in tools/rca/."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class CorrelateArgs(BaseModel):
    table: str = "wafer_defects"     # a loaded SQL table
    target: str = "defect_label"     # the column to explain (defect / yield)


class CorrelateResult(BaseModel):
    target: str
    ranking: list[dict]              # [{parameter, r}], strongest first


@tool("correlate_params_vs_yield",
      "Rank process parameters by absolute correlation with the defect/yield "
      "target column in a loaded table. Use to find which parameters drive defects.",
      CorrelateArgs, returns=CorrelateResult, owner="rca-core", tags=["analysis", "yield"])
def correlate_params_vs_yield(table="wafer_defects", target="defect_label"):
    try:
        cols, rows = datastore.run_sql(f'select * from "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'. Upload a defect/process dataset first."
    df = pd.DataFrame(rows, columns=cols).apply(pd.to_numeric, errors="coerce")
    if target not in df.columns:
        return f"Target column '{target}' not found. Columns: {', '.join(cols)}"
    corr = df.corr(numeric_only=True).get(target)
    if corr is None:
        return f"No numeric correlation could be computed against '{target}'."
    corr = corr.drop(labels=[target], errors="ignore").dropna()
    ranked = corr.abs().sort_values(ascending=False)
    lines = [f"  {p}: r={corr[p]:+.3f}" for p in ranked.index]
    top = ranked.index[0] if len(ranked) else "(none)"
    return (f"Correlation of process parameters with '{target}' in '{table}' "
            f"(strongest first):\n" + "\n".join(lines) +
            f"\n\nStrongest driver: {top}.")
