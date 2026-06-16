"""Skill: match a user's role/persona to the analyzer personas, and check whether the
dataset ACTUALLY supports that role.

This is a MATCHING routine, not data analysis — so it is a skill, not an analysis tool,
and its result is advisory (which persona fits), never citable as evidence for a data
claim. Crucially it is TRUTHFUL: it reads the dataset's REAL columns from the datastore
itself (scope-respecting) instead of trusting a column list passed in by an agent, which
could be hallucinated. So "found/missing fields" reflects what is actually in the table.
"""
from core.declare import skill
from connectors import datastore
from agents.aneetta.analyzer import check_dataset_support


def _real_columns(dataset_id=""):
    """The ACTUAL column names of the dataset, read from the datastore (honours the
    run's data scope). `dataset_id` selects a table/source by name; blank = first visible
    table. Returns [] if nothing is in scope, so the matcher reports honest 'missing'."""
    want = (dataset_id or "").strip()
    for s in datastore.list_sources():                  # scope-respecting
        for tbl in s.get("tables", []):
            if not want or tbl == want or s["name"] == want:
                try:
                    cols, _ = datastore.run_sql(f'SELECT * FROM "{tbl}" LIMIT 0',
                                                source=s["name"])
                    return list(cols), tbl
                except Exception:
                    continue
    return [], want


@skill("yield_persona_support",
       "Match a semiconductor user role/group to analyzer personas and check whether the "
       "dataset's REAL columns support that role. Reads the actual schema itself — pass the "
       "user's question and (optionally) the dataset/table name.",
       limits="Advisory role/persona matching only; reads column NAMES (real schema), not "
              "row data, and runs no statistical analysis. Not evidence for a data finding.")
def yield_persona_support(user_text, dataset_id=""):
    real_cols, table = _real_columns(dataset_id)
    result = check_dataset_support(user_text=user_text, dataset_columns=real_cols)
    result["dataset_id"] = table or dataset_id
    result["dataset_columns_checked"] = real_cols           # the TRUTH it matched against
    result["schema_source"] = "actual dataset columns (read from the datastore)"
    if not real_cols:
        result["warning"] = ("no dataset is in scope — role match is based on the question "
                             "only; upload/select a dataset for a real column check")
    return result
