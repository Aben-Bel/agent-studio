"""Skill: multi-dimensional defect pattern analysis.

A multi-step routine for the Defect Inspection Engineer: profiles defects
across type, zone, and process step in one call, then computes a co-occurrence
table showing which combinations are most frequent. Replaces several individual
queries the engineer would otherwise run manually."""
from core.declare import skill
from connectors import datastore
import pandas as pd


@skill(
    "analyze_defect_patterns",
    "Profile defects across type, wafer zone, and process step in one pass. "
    "Returns per-dimension breakdowns and a top-10 co-occurrence table so the "
    "engineer can spot which (type × zone) or (type × step) combinations dominate.",
)
def analyze_defect_patterns(
    table: str = "wafer_defects",
    defect_type_col: str = "defect_type",
    zone_col: str = "wafer_zone",
    step_col: str = "process_step",
    count_col: str = "defect_count",
) -> str:
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    total_rows = len(df)
    lines = [f"Defect pattern analysis — table: {table}  |  Rows: {total_rows}"]

    # Numeric count column
    has_count = count_col in df.columns
    if has_count:
        df[count_col] = pd.to_numeric(df[count_col], errors="coerce").fillna(0)

    def breakdown(col_name, label):
        if col_name not in df.columns:
            return f"\n[{label}]: column '{col_name}' not found — skipped."
        if has_count:
            grp = (df.groupby(col_name)[count_col].sum()
                   .reset_index(name="defects")
                   .sort_values("defects", ascending=False)
                   .head(10))
            grp["pct"] = (grp["defects"] / grp["defects"].sum() * 100).round(1)
        else:
            grp = (df.groupby(col_name).size()
                   .reset_index(name="defects")
                   .sort_values("defects", ascending=False)
                   .head(10))
            grp["pct"] = (grp["defects"] / grp["defects"].sum() * 100).round(1)
        return f"\n{label} breakdown (top 10):\n{grp.to_string(index=False)}"

    lines.append(breakdown(defect_type_col, "Defect type"))
    lines.append(breakdown(zone_col, "Wafer zone"))
    lines.append(breakdown(step_col, "Process step"))

    # Co-occurrence: defect_type × zone (most actionable combination)
    avail_pair = [c for c in [defect_type_col, zone_col] if c in df.columns]
    if len(avail_pair) == 2:
        if has_count:
            co = (df.groupby(avail_pair)[count_col].sum()
                  .reset_index(name="defects")
                  .sort_values("defects", ascending=False)
                  .head(10))
        else:
            co = (df.groupby(avail_pair).size()
                  .reset_index(name="defects")
                  .sort_values("defects", ascending=False)
                  .head(10))
        lines.append(f"\nTop 10 co-occurrences ({defect_type_col} × {zone_col}):\n"
                     f"{co.to_string(index=False)}")

    return "\n".join(lines)
