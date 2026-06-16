# tools/laure/load_uploaded_csv.py
from pydantic import BaseModel
from core.declare import tool
from connectors import datastore
import pandas as pd

class Empty(BaseModel):
    name: str | None = None   # optional: which uploaded file/table to load (default: most recent)

@tool("load_uploaded_csv", "Load and return the contents of an uploaded CSV. Pass `name` to pick a specific file/table when several were uploaded; omit it for the most recent.", Empty, owner="laure",
      limits="Loads already-uploaded CSVs only; cannot fetch URLs, connect databases, or parse non-CSV files.")
def load_uploaded_csv(name=None):
    # datastore.get_uploaded_file() should return a path or file-like object
    file_path = datastore.get_uploaded_file(name)
    if not file_path:
        return "No file uploaded yet."
    try:
        df = pd.read_csv(file_path)
        # return a compact structure the LLM can consume
        return {
            "n_rows": len(df),
            "n_cols": len(df.columns),
            "columns": df.columns.tolist(),
            "preview": df.head(10).to_dict(orient="records")
        }
    except Exception as e:
        return f"Failed to read CSV: {e}"
