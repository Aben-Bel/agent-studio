"""Skill: full defect risk profile in one call.

Runs compare_process_steps + summarize_defect_distribution + yield_trend
in sequence and returns a complete defect risk summary. Replaces 3 manual
tool calls with a single orchestrated routine for the defect_profiler agent."""
import pandas as pd
from core.declare import skill
from connectors import datastore


@skill(
    "defect_risk_profile",
    "Run a complete defect risk profile in one call: process step ranking, "
    "defect distribution, and yield trend pattern. Returns a consolidated "
    "summary so the agent does not need to chain 3 tool calls manually.",
    limits="Descriptive single-table profile; ranks worst step by raw rate without a significance test or causal claim.",
)
def defect_risk_profile(
    table: str = "wafer_defects",
    step_col: str = "process_step",
    defect_col: str = "defect_label",
    wafer_col: str = "wafer_id",
    windows: int = 5,
) -> str:
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    df[defect_col] = pd.to_numeric(df[defect_col], errors="coerce").fillna(0)
    total = len(df)
    overall_rate = df[defect_col].mean() * 100
    lines = [
        f"=== DEFECT RISK PROFILE — {table} ===",
        f"Total wafers: {total}  |  Overall defect rate: {overall_rate:.2f}%",
        "",
    ]

    # 1. Process step ranking
    if step_col in df.columns:
        grp = (
            df.groupby(step_col)
            .agg(total=(defect_col, "count"), defects=(defect_col, "sum"))
            .reset_index()
        )
        grp["rate_%"] = (grp["defects"] / grp["total"] * 100).round(2)
        grp = grp.sort_values("rate_%", ascending=False)
        worst_step = grp.iloc[0]
        lines += [
            "1. PROCESS STEP RANKING",
            grp.to_string(index=False),
            f"   → Worst step: {worst_step[step_col]} ({worst_step['rate_%']}%)",
            "",
        ]
    else:
        lines += [f"1. PROCESS STEP RANKING — column '{step_col}' not found.", ""]

    # 2. Yield trend
    if wafer_col in df.columns:
        df[wafer_col] = pd.to_numeric(df[wafer_col], errors="coerce")
        df_sorted = df.dropna(subset=[wafer_col]).sort_values(wafer_col)
        df_sorted["window"] = pd.cut(
            df_sorted[wafer_col], bins=windows,
            labels=[f"W{i+1}" for i in range(windows)]
        )
        trend = (
            df_sorted.groupby("window", observed=True)
            .agg(wafers=(wafer_col, "count"), defects=(defect_col, "sum"))
            .reset_index()
        )
        trend["rate_%"] = (trend["defects"] / trend["wafers"] * 100).round(2)
        rates = trend["rate_%"].tolist()
        peak = trend.loc[trend["rate_%"].idxmax()]
        avg = sum(rates) / len(rates) if rates else 0
        if rates[-1] > rates[0] + 3:
            pattern = "DRIFT — rate rising over time"
        elif peak["rate_%"] > avg * 1.5 and avg > 0:
            pattern = f"EXCURSION — spike in {peak['window']} ({peak['rate_%']}%)"
        else:
            pattern = "STABLE — no significant drift or excursion"
        lines += [
            "2. YIELD TREND",
            trend.to_string(index=False),
            f"   → Pattern: {pattern}",
            "",
        ]
    else:
        lines += [f"2. YIELD TREND — column '{wafer_col}' not found.", ""]

    # 3. Risk summary
    lines += [
        "3. RISK SUMMARY",
        f"   Worst process step : {worst_step[step_col] if step_col in df.columns else 'unknown'} "
        f"({worst_step['rate_%'] if step_col in df.columns else 'N/A'}% defect rate)",
        f"   Trend pattern      : {pattern if wafer_col in df.columns else 'unknown'}",
        f"   Overall defect rate: {overall_rate:.2f}%",
    ]
    return "\n".join(lines)
