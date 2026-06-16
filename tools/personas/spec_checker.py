"""Tool: check measurement values against spec / control limits in a loaded table.

Real implementation — reads the table via SQLAlchemy, compares value_col against
spec_col and control_col row-by-row, and returns a summary of violations."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class SpecArgs(BaseModel):
    table: str = "wafer_defects"
    value_col: str = "measurement_value"
    spec_col: str = "spec_limit"
    control_col: str = "control_limit"
    group_by: str = ""          # optional: column to group violation counts by (e.g. "process_step")


@tool(
    "check_spec_limits",
    "Compare a measurement column against spec and control limits in a loaded table. "
    "Returns count and % of rows in violation, worst offenders, and optionally a "
    "per-group breakdown. Use for quality / metrology analysis.",
    SpecArgs,
    owner="personas",
    tags=["quality", "metrology", "spec"],
)
def check_spec_limits(
    table="wafer_defects",
    value_col="measurement_value",
    spec_col="spec_limit",
    control_col="control_limit",
    group_by="",
):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)

    missing = [c for c in [value_col, spec_col] if c not in df.columns]
    if missing:
        available = ", ".join(df.columns.tolist())
        return (f"Column(s) not found: {', '.join(missing)}. "
                f"Available columns: {available}")

    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df[spec_col] = pd.to_numeric(df[spec_col], errors="coerce")

    spec_breach = df[value_col] > df[spec_col]
    total = len(df)
    spec_violations = int(spec_breach.sum())
    lines = [
        f"Table: {table}  |  Rows: {total}",
        f"Spec limit ({spec_col}) breaches: {spec_violations} "
        f"({spec_violations / total * 100:.1f}%)",
    ]

    if control_col in df.columns:
        df[control_col] = pd.to_numeric(df[control_col], errors="coerce")
        ctrl_breach = df[value_col] > df[control_col]
        ctrl_violations = int(ctrl_breach.sum())
        lines.append(
            f"Control limit ({control_col}) breaches: {ctrl_violations} "
            f"({ctrl_violations / total * 100:.1f}%)"
        )

    # Worst offenders: rows where value exceeds spec by the most
    df["_excess"] = df[value_col] - df[spec_col]
    worst = df.nlargest(5, "_excess")[[value_col, spec_col, "_excess"]]
    if not worst.empty:
        lines.append(f"\nTop 5 worst spec breaches ({value_col} - {spec_col}):")
        lines.append(worst.to_string(index=False))

    # Optional group breakdown
    if group_by and group_by in df.columns:
        grp = (
            df[spec_breach]
            .groupby(group_by)
            .size()
            .reset_index(name="violations")
            .sort_values("violations", ascending=False)
        )
        if not grp.empty:
            lines.append(f"\nViolations by {group_by}:")
            lines.append(grp.to_string(index=False))

    return "\n".join(lines)
