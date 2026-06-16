"""Tools: descriptive statistics and outlier detection for a loaded table.

Both are real pandas implementations that work against any table in the
SQLAlchemy datastore. Used primarily by the Data Scientist / Statistical
Analyst persona agent."""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore


class SummaryArgs(BaseModel):
    table: str = "wafer_defects"
    columns: str = ""       # comma-separated; leave blank for all numeric columns


class OutlierArgs(BaseModel):
    table: str = "wafer_defects"
    column: str             # the numeric column to inspect
    method: str = "iqr"     # "iqr" or "zscore"
    threshold: float = 3.0  # z-score threshold (ignored for iqr)


@tool(
    "compute_summary_stats",
    "Return descriptive statistics (count, mean, std, min, quartiles, max) for "
    "numeric columns in a loaded table. Pass a comma-separated list to `columns` "
    "to focus on specific ones, or leave blank for all numeric columns.",
    SummaryArgs,
    owner="personas",
    tags=["statistics", "data-science"],
    limits="Describes numeric columns only; no correlation, hypothesis testing, or causal inference.",
)
def compute_summary_stats(table="wafer_defects", columns=""):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    if columns:
        wanted = [c.strip() for c in columns.split(",") if c.strip()]
        missing = [c for c in wanted if c not in df.columns]
        if missing:
            return f"Columns not found: {', '.join(missing)}. Available: {', '.join(df.columns)}"
        df = df[wanted]

    numeric = df.select_dtypes(include="number")
    if numeric.empty:
        return f"No numeric columns found in '{table}'."

    desc = numeric.describe().round(4)
    return f"Summary statistics for '{table}':\n{desc.to_string()}"


@tool(
    "detect_outliers",
    "Detect statistical outliers in a numeric column using IQR fences (method='iqr') "
    "or z-score (method='zscore', threshold=3.0). Returns outlier rows and summary.",
    OutlierArgs,
    owner="personas",
    tags=["statistics", "anomaly", "data-science"],
    limits="Flags outliers in one numeric column by IQR/z-score; does not explain or attribute a cause.",
)
def detect_outliers(table="wafer_defects", column="", method="iqr", threshold=3.0):
    try:
        cols, rows = datastore.run_sql(f'SELECT * FROM "{table}"')
    except Exception as e:
        return f"Could not read table '{table}': {e}"
    if not rows:
        return f"No rows in '{table}'."

    df = pd.DataFrame(rows, columns=cols)
    if column not in df.columns:
        return f"Column '{column}' not found. Available: {', '.join(df.columns)}"

    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return f"No numeric values in column '{column}'."

    if method == "zscore":
        z = (series - series.mean()) / series.std()
        mask = z.abs() > threshold
        label = f"|z| > {threshold}"
    else:
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = (series < lo) | (series > hi)
        label = f"outside [{lo:.4f}, {hi:.4f}]"

    outlier_idx = mask[mask].index
    n_out = len(outlier_idx)
    lines = [
        f"Outlier detection — table: {table}, column: {column}, method: {method}",
        f"Total rows: {len(series)}  |  Outliers ({label}): {n_out} "
        f"({n_out / len(series) * 100:.1f}%)",
    ]
    if n_out:
        sample = df.loc[outlier_idx[:10], [column]]
        lines.append(f"\nSample outlier rows (up to 10):\n{sample.to_string()}")
    return "\n".join(lines)
