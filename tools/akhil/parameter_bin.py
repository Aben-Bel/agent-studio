"""Tool: bucket a numeric parameter into ranges and show defect rate per bucket.

Answers 'at what temperature / pressure / gas_flow range do defects spike?'
— the key insight for a process engineer deciding where to tighten tolerances."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class ParamBinArgs(BaseModel):
    table: str = "wafer_defects"
    parameter: str = "temperature_c"
    defect_col: str = "defect_label"
    bins: int = 5


@tool(
    "parameter_bin_analysis",
    "Bucket a numeric process parameter into equal-width ranges and compute the "
    "defect rate per bucket. Reveals at which value range defects spike — e.g. "
    "'temperature above 465°C has 5x higher defect rate'. Use to find the danger "
    "zone for any parameter.",
    ParamBinArgs,
    owner="akhil",
    tags=["defect", "parameter", "binning", "yield"],
)
def parameter_bin_analysis(
    table="wafer_defects",
    parameter="temperature_c",
    defect_col="defect_label",
    bins=5,
):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    missing = [c for c in [parameter, defect_col] if c not in df.columns]
    if missing:
        return (f"Column(s) not found: {', '.join(missing)}. "
                f"Available: {', '.join(df.columns)}")

    df[parameter] = pd.to_numeric(df[parameter], errors="coerce")
    df[defect_col] = pd.to_numeric(df[defect_col], errors="coerce").fillna(0)
    df = df.dropna(subset=[parameter])

    df["range"] = pd.cut(df[parameter], bins=bins)
    grp = (
        df.groupby("range", observed=True)
        .agg(wafers=(defect_col, "count"), defects=(defect_col, "sum"))
        .reset_index()
    )
    grp["defect_rate_%"] = (grp["defects"] / grp["wafers"] * 100).round(3)
    grp["range"] = grp["range"].astype(str)

    worst = grp.loc[grp["defect_rate_%"].idxmax()]
    baseline = grp["defect_rate_%"].replace(0, float("nan")).min()
    multiplier = ""
    if baseline and baseline > 0 and worst["defect_rate_%"] > 0:
        mult = worst["defect_rate_%"] / baseline
        multiplier = f" ({mult:.1f}x baseline rate)"

    lines = [
        f"Parameter bin analysis — {parameter} vs {defect_col} | table: {table}",
        "",
        grp.to_string(index=False),
        "",
        f"Danger zone: {worst['range']} → {worst['defect_rate_%']}% defect rate{multiplier}",
    ]
    return "\n".join(lines)
