"""RCA tool: test process-step / parameter association with the defect outcome.

This is the deterministic 'analysis script' the engineer runs by hand today — but
made statistically honest. It does NOT report a bare correlation and crown a
"strongest driver"; that manufactures findings out of sampling noise. Instead it runs
a real per-group hypothesis test (see tools/rca/stats_core.py) and returns either a
tested, effect-sized, FDR-corrected finding OR an explicit "no significant
association" / "insufficient data" result.

Contract: ONE categorical grouping column (e.g. process_step) and ONE binary 0/1
outcome column (e.g. defect_label). Both are arguments resolved at call time — no
column names are hardcoded; defaults are only fallbacks for the seeded demo table.
"""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore
from tools.rca import stats_core as sc


class CorrelateArgs(BaseModel):
    table: str = "wafer_defects"          # a loaded SQL table
    group_col: str = ""                    # categorical column to test (e.g. process_step); blank = infer
    outcome_col: str = ""                  # binary 0/1 outcome (e.g. defect_label); blank = infer


class CorrelateResult(BaseModel):
    kind: str                              # finding | no_significant_association | insufficient_data | incompatible_data
    group_col: str = ""
    outcome_col: str = ""
    summary: str                           # the rendered honest text
    detail: dict = {}                      # the full structured scan (for exporters / the UI)


@tool("correlate_params_vs_yield",
      "Test which process STEP (or other categorical column) is associated with a binary "
      "defect/yield outcome, using a real per-group hypothesis test with effect sizes, "
      "Wilson CIs and FDR correction. Returns flagged groups ONLY when a test passes, "
      "otherwise an explicit 'no significant association' or 'insufficient data' result — "
      "it never invents a 'strongest driver'. Args: table, group_col (categorical, blank "
      "to infer), outcome_col (binary 0/1, blank to infer).",
      CorrelateArgs, returns=CorrelateResult, owner="rca-core", tags=["analysis", "yield", "stats"])
def correlate_params_vs_yield(table="wafer_defects", group_col="", outcome_col=""):
    try:
        cols, rows = datastore.run_sql(f'select * from "{table}"')
    except Exception as e:
        return {"kind": sc.KIND_INCOMPATIBLE, "summary": f"Could not read table '{table}': {e}",
                "detail": {}}
    if not rows:
        return {"kind": sc.KIND_INCOMPATIBLE,
                "summary": f"No rows in '{table}'. Upload a defect/process dataset first.",
                "detail": {}}
    df = pd.DataFrame(rows, columns=cols)

    # Resolve the contract (typed args first, then inference; ambiguity => structured incompatible).
    oc, err = sc.resolve_outcome(df, outcome_col or None)
    if err:
        return {"kind": sc.KIND_INCOMPATIBLE, "summary": f"Incompatible data: {err}.",
                "detail": {"reason": err}}
    gc, err = sc.resolve_group(df, group_col or None, oc)
    if err:
        return {"kind": sc.KIND_INCOMPATIBLE, "summary": f"Incompatible data: {err}.",
                "detail": {"reason": err}}

    res = sc.group_vs_rest_scan(df, gc, oc)
    return {"kind": res["kind"], "group_col": gc, "outcome_col": oc,
            "summary": sc.render_scan(res), "detail": res}
