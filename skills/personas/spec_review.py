"""Skill: full spec-limit review across all numeric columns in a table.

A multi-step routine for the Quality / Metrology Engineer: lists available
data, identifies columns that look like measurement/spec pairs by name
convention, and returns a compact compliance summary — all without the agent
having to write individual SQL queries."""
from core.declare import skill
from connectors import datastore
import pandas as pd


@skill(
    "run_full_spec_review",
    "Run a comprehensive spec-limit compliance review on a loaded table. "
    "Finds candidate (value, spec_limit, control_limit) column pairs by naming "
    "convention, checks each pair, and returns a pass/fail summary table. "
    "Faster than querying each column individually.",
    limits="Detects value/spec pairs by column-name convention; may miss oddly named columns and asserts no cause.",
)
def run_full_spec_review(table: str = "wafer_defects") -> str:
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        return f"No numeric columns found in '{table}'."

    # Identify likely value/spec pairs by name similarity
    spec_keywords = ["spec_limit", "spec", "upper_limit", "usl", "ucl", "lsl", "lcl"]
    ctrl_keywords = ["control_limit", "control", "ucl", "lcl"]
    spec_cols = [c for c in cols if any(k in c.lower() for k in spec_keywords)]
    ctrl_cols = [c for c in cols if any(k in c.lower() for k in ctrl_keywords)]

    # Value columns are numeric columns NOT identified as limits
    limit_cols = set(spec_cols + ctrl_cols)
    value_cols = [c for c in numeric_cols if c not in limit_cols]

    if not value_cols:
        # Fall back: just report descriptive stats
        desc = df[numeric_cols].describe().round(3)
        return (f"No clear value/spec column pairs detected in '{table}'. "
                f"Descriptive stats:\n{desc.to_string()}")

    total = len(df)
    report_rows = []
    for vcol in value_cols:
        series = pd.to_numeric(df[vcol], errors="coerce")
        row = {
            "column": vcol,
            "mean": round(float(series.mean()), 4),
            "std": round(float(series.std()), 4),
            "min": round(float(series.min()), 4),
            "max": round(float(series.max()), 4),
        }
        # Check against first matching spec col
        for scol in spec_cols:
            if scol in df.columns:
                slimit = pd.to_numeric(df[scol], errors="coerce")
                breaches = int((series > slimit).sum())
                row["spec_col"] = scol
                row["spec_breaches"] = breaches
                row["spec_breach_pct"] = f"{breaches / total * 100:.1f}%"
                break
        report_rows.append(row)

    result_df = pd.DataFrame(report_rows)
    lines = [
        f"Full spec review — table: {table}  |  Total rows: {total}",
        f"Spec limit columns detected: {spec_cols or 'none'}",
        f"Control limit columns detected: {ctrl_cols or 'none'}",
        "",
        result_df.to_string(index=False),
    ]
    return "\n".join(lines)
