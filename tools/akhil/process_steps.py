"""Tool: compare defect rates across process steps — with a real significance test.

Groups the dataset by process_step and shows the per-step defect rate, but it does
NOT crown a "worst step" from a bare rate sort (that manufactures a culprit even on
pure noise). The descriptive table is kept; the *claim* of which step is associated
with defects is delegated to the shared honest stats core, which flags a step only
when a per-group test passes (effect size + FDR-adjusted p), else reports no
significant association."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore
from tools.rca import stats_core as sc


class ProcessStepArgs(BaseModel):
    table: str = "wafer_defects"
    step_col: str = "process_step"        # categorical grouping column; blank to infer
    defect_col: str = "defect_label"      # binary 0/1 outcome; blank to infer


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

    # Resolve the contract: a categorical step column + a binary 0/1 outcome.
    oc, err = sc.resolve_outcome(df, defect_col or None)
    if err:
        return f"Incompatible data: {err}."
    gc, err = sc.resolve_group(df, step_col or None, oc)
    if err:
        return f"Incompatible data: {err}."

    df[oc] = pd.to_numeric(df[oc], errors="coerce")

    grp = (
        df.groupby(gc)
        .agg(total_wafers=(oc, "count"), defect_count=(oc, "sum"))
        .reset_index()
    )
    grp["defect_rate_%"] = (grp["defect_count"] / grp["total_wafers"] * 100).round(2)
    grp = grp.sort_values("defect_rate_%", ascending=False)

    # The honest verdict: a step is called out ONLY if a per-group test flags it.
    res = sc.group_vs_rest_scan(df, gc, oc)

    lines = [
        f"Process step defect comparison — table: {table}",
        f"Total wafers: {len(df)}  |  Overall defect rate: {df[oc].mean() * 100:.2f}%",
        "",
        grp.to_string(index=False),
        "",
        sc.render_scan(res),
    ]
    return "\n".join(lines)
