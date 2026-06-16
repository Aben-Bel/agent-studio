"""Tool: Statistical Process Control (SPC) check.

For each numeric parameter, computes the mean and 3-sigma (3σ) control
limits and flags wafers that fall outside. This is the standard SPC
control chart used in every semiconductor fab. Out-of-control points
indicate the process is not behaving predictably."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class SpcArgs(BaseModel):
    table: str = "wafer_defects"
    columns: str = ""       # comma-separated numeric columns; blank = all numeric
    sigma: float = 3.0      # control limit multiplier (default 3σ)


@tool(
    "spc_check",
    "Run a Statistical Process Control (SPC) check on numeric process parameters. "
    "Computes mean ± N-sigma control limits for each parameter and reports how many "
    "wafers are out of control and which ones. Standard fab technique to detect "
    "parameters that are statistically unstable.",
    SpcArgs,
    owner="akhil",
    tags=["spc", "control-chart", "statistics", "quality"],
    limits="Flags out-of-control points on numeric columns only; does not diagnose why or imply a cause.",
)
def spc_check(table="wafer_defects", columns="", sigma=3.0):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)

    # SQLite returns all values as strings — force-convert every column to numeric
    # and keep only the ones that have at least some valid numbers.
    if columns:
        wanted = [c.strip() for c in columns.split(",") if c.strip()]
        missing = [c for c in wanted if c not in df.columns]
        if missing:
            return f"Columns not found: {', '.join(missing)}. Available: {', '.join(df.columns)}"
        numeric = df[wanted].apply(pd.to_numeric, errors="coerce")
    else:
        numeric = df.apply(pd.to_numeric, errors="coerce")

    numeric = numeric.loc[:, numeric.notna().any()]
    if numeric.empty:
        return f"No numeric columns found in '{table}'."

    total = len(df)
    report_rows = []
    for col in numeric.columns:
        series = numeric[col].dropna()
        if len(series) < 2:
            continue
        mean = series.mean()
        std = series.std()
        ucl = mean + sigma * std
        lcl = mean - sigma * std
        out_of_control = ((series > ucl) | (series < lcl)).sum()
        report_rows.append({
            "parameter": col,
            "mean": round(mean, 4),
            "std": round(std, 4),
            f"LCL ({sigma}σ)": round(lcl, 4),
            f"UCL ({sigma}σ)": round(ucl, 4),
            "out_of_control": int(out_of_control),
            "ooc_%": round(out_of_control / total * 100, 2),
        })

    if not report_rows:
        return "No parameters with enough data for SPC analysis."

    result = pd.DataFrame(report_rows).sort_values("ooc_%", ascending=False)
    worst = result.iloc[0]

    lines = [
        f"SPC check — table: {table}  |  Control limits: ±{sigma}σ  |  Total wafers: {total}",
        "",
        result.to_string(index=False),
        "",
        f"Most unstable parameter: {worst['parameter']} "
        f"({worst['ooc_%']}% of wafers outside {sigma}σ limits)",
    ]
    return "\n".join(lines)
