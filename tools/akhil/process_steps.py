"""Tool: compare defect rates across process steps.

Groups the dataset by process_step, computes defect rate per step,
and ranks them worst to best. Directly answers 'which step is causing
the most defects?' without the agent needing to write SQL."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class ProcessStepArgs(BaseModel):
    table: str = "wafer_defects"
    step_col: str = "process_step"
    defect_col: str = "defect_label"


@tool(
    "compare_process_steps",
    "Compare defect rates across all process steps (e.g. Deposition, Lithography, "
    "Etching, Oxidation, CMP). Returns defect count, total wafers, and defect rate % "
    "per step, ranked worst to best. Use to identify which production step drives yield loss.",
    ProcessStepArgs,
    owner="akhil",
    tags=["process", "yield", "defect", "step"],
)
def compare_process_steps(
    table="wafer_defects",
    step_col="process_step",
    defect_col="defect_label",
):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)

    missing = [c for c in [step_col, defect_col] if c not in df.columns]
    if missing:
        return (f"Column(s) not found: {', '.join(missing)}. "
                f"Available: {', '.join(df.columns)}")

    df[defect_col] = pd.to_numeric(df[defect_col], errors="coerce").fillna(0)

    grp = (
        df.groupby(step_col)
        .agg(
            total_wafers=(defect_col, "count"),
            defect_count=(defect_col, "sum"),
        )
        .reset_index()
    )
    grp["defect_rate_%"] = (grp["defect_count"] / grp["total_wafers"] * 100).round(2)
    grp = grp.sort_values("defect_rate_%", ascending=False)

    worst = grp.iloc[0]
    best = grp.iloc[-1]

    lines = [
        f"Process step defect comparison — table: {table}",
        f"Total wafers: {len(df)}  |  Overall defect rate: "
        f"{df[defect_col].mean() * 100:.2f}%",
        "",
        grp.to_string(index=False),
        "",
        f"Worst step : {worst[step_col]} ({worst['defect_rate_%']}% defect rate)",
        f"Best step  : {best[step_col]} ({best['defect_rate_%']}% defect rate)",
    ]
    return "\n".join(lines)
