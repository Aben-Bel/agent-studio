"""Seed the sample data so the platform demos before any upload:
- the semiconductor wafer/defect dataset -> a queryable SQL table
- the failure-mode manual -> the vector RAG store (via the ingestion pipeline)
"""
import os
from core.discovery import discover
from connectors import datastore
from core import pipeline

discover()   # register pipeline @stage files so run_pending actually indexes

SEARCH_DIRS = ["data/sources", "sources"]


def _find(name):
    for d in SEARCH_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


# 1) defect / process dataset -> SQL table the RCA tools query
wafer = _find("semiconductor_wafer_defect_dataset.csv")
if wafer:
    info = datastore.load_csv(wafer, "wafer_defects")
    print(f"loaded {info['rows']} rows into the 'wafer_defects' table")
else:
    print("no wafer dataset found; correlate_params_vs_yield will have no data")

# 2) manuals / FMEA docs -> RAG (run through the same pipeline as an upload)
for name in ("fab_process_manual.md",):
    path = _find(name)
    if not path:
        print(f"skipped {name} (not found)")
        continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        pipeline.add_upload(name, f.read())
    print(f"queued {name} for indexing")
processed = pipeline.run_pending()
print(f"indexed {len(processed)} document(s) into the RAG store")
