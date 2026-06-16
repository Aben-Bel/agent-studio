"""RCA tool: which CONTINUOUS parameter drives the outcome, WITHIN a row scope.

This is the within-scope univariate driver search that `correlate_params_vs_yield`
(categorical group-vs-rest) and `confounder_check` (a pairwise conditioning test) are
NOT. For a given subset of rows (e.g. one lot, or one process step), it tests each
candidate continuous parameter for association with the binary outcome — median split →
two-proportion test, effect size + Wilson CI + BH-FDR across the parameter family — and
then demotes any flagged-but-confounded parameter. It returns the same structured `kind`
discriminator as the rest of the honest stats core, so a finding / null / insufficient is
never blurred.

Contract: a binary 0/1 outcome (blank to infer) + an OPTIONAL scope ({column, values})
that restricts the rows. No column names are hardcoded; defaults are demo fallbacks.
"""
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore
from tools.rca import stats_core as sc


class DriverArgs(BaseModel):
    table: str = "wafer_defects"
    outcome_col: str = ""                  # binary 0/1 outcome; blank = infer
    params: str = ""                       # comma-separated parameters to test; blank = all numeric
    # Restrict the test to a subset, e.g. {"column": <col>, "values": [<value>]}
    # or a list of such filters. Validated column+values, never raw SQL.
    scope: Optional[Any] = None
    # Optional grouping column to exclude from the parameter set + label the scope.
    group_col: str = ""


class DriverResult(BaseModel):
    kind: str                              # finding | no_significant_association | insufficient_data | incompatible_data
    outcome_col: str = ""
    scope: list = []
    summary: str
    detail: dict = {}


@tool("driver_within_scope",
      "Find which CONTINUOUS process parameter is associated with the binary defect/yield "
      "outcome WITHIN a row scope (e.g. inside one lot or one process step). Median-split "
      "two-proportion test per parameter with effect size, Wilson CI, BH-FDR, then a "
      "confounder pass that demotes parameters not independently predictive. Returns a "
      "flagged driver ONLY when a test passes, else an explicit null / insufficient result. "
      "Args: table, outcome_col (blank to infer), params (comma list, blank=all numeric), "
      "scope ({column, values} to restrict rows), group_col (optional).",
      DriverArgs, returns=DriverResult, owner="rca-core", tags=["analysis", "yield", "stats", "driver"],
      limits="Within-scope association, not causation; needs a binary outcome and enough non-degenerate rows in scope.")
def driver_within_scope(table="wafer_defects", outcome_col="", params="", scope=None, group_col=""):
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

    df, scope_labels, serr, resolved_scope = sc.apply_scope(df, scope)
    if serr:
        return {"kind": sc.KIND_INCOMPATIBLE, "summary": f"Invalid scope: {serr}.",
                "detail": {"reason": serr}}
    if scope and not len(df):
        return {"kind": sc.KIND_INCOMPATIBLE,
                "summary": f"Scope {scope_labels} matched no rows in '{table}'.",
                "detail": {"scope": scope_labels}}

    oc, err = sc.resolve_outcome(df, outcome_col or None)
    if err:
        return {"kind": sc.KIND_INCOMPATIBLE, "summary": f"Incompatible data: {err}.",
                "detail": {"reason": err}}

    plist = [p.strip() for p in params.split(",") if p.strip()] or None
    res = sc.driver_scan(df, oc, params=plist, group_col=group_col or None)
    res["scope_labels"] = scope_labels
    # Expose the RESOLVED scope (canonical real values) so the orchestrator records the
    # same value the analysis ran on — not the agent's raw guess ('C' vs 'LOT_C').
    return {"kind": res["kind"], "outcome_col": oc, "scope": scope_labels,
            "summary": sc.render_driver(res), "detail": res,
            "resolved_scope": resolved_scope}
