"""Intake / readiness check: is the visible data actually analyzable BEFORE we route
specialists at it? Inventories every visible source (tables, columns, dtypes, row
counts) and, for the association stats path, checks the contract a real test needs:
a categorical grouping column, a binary 0/1 outcome, n >= MIN_GROUP_N, and non-zero
outcome variance.

It returns a structured verdict — ready | ambiguous | insufficient | empty — so the
readiness agent can either hand off cleanly or ask the human to fix the data. It never
asserts a finding and never asks for ground truth; it confirms data CORRECTNESS only.
"""
import pandas as pd
from pydantic import BaseModel
from core.declare import tool
from core.config import cfg
from connectors import datastore
from tools.rca import stats_core as sc


# Verdict kinds (stable strings for the agent + UI)
READY = "ready"
AMBIGUOUS = "ambiguous"          # data exists but column roles can't be resolved
INSUFFICIENT = "insufficient"    # data exists but cannot support a test (n / variance)
EMPTY = "empty"                  # no rows / no tables anywhere


class ReadinessArgs(BaseModel):
    sources: str = ""            # optional comma-separated source names to limit the scan; blank = all


class ReadinessResult(BaseModel):
    verdict: str                 # ready | ambiguous | insufficient | empty
    summary: str                 # the human-facing inventory + verdict text
    inventory: list = []         # [{source, table, n_rows, columns:[{name, dtype}]}]
    reasons: list = []           # per-table reasons when not ready
    signature: str = ""          # fingerprint of the data shape — used to detect "sources changed"


def _infer_dtype(s: pd.Series) -> str:
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() > 0.95:
        v = set(num.dropna().unique())
        return "binary" if v and v.issubset({0, 1}) else "numeric"
    return "categorical"


@tool("check_readiness",
      "Inventory every visible data source (tables, columns, dtypes, row counts) and check, "
      "per the association stats contract, whether the data can support a real test "
      "(categorical group column + binary 0/1 outcome + enough rows + non-zero variance). "
      "Returns a structured verdict: ready | ambiguous | insufficient | empty. Use at intake, "
      "before routing analysis specialists. Confirms data correctness only — never a finding.",
      ReadinessArgs, returns=ReadinessResult, owner="rca-core", tags=["intake", "readiness"])
def check_readiness(sources=""):
    wanted = {s.strip() for s in sources.split(",") if s.strip()} or None
    inventory, reasons = [], []
    ready_tables, ambiguous, insufficient = [], [], []
    sig_parts = []

    src_list = [s for s in datastore.list_sources()
                if (wanted is None or s["name"] in wanted)]
    for s in src_list:
        for tbl in s.get("tables", []):
            try:
                cols, rows = datastore.run_sql(f'SELECT * FROM "{tbl}"', source=s["name"])
            except Exception as e:
                reasons.append(f"{tbl}: unreadable ({e})")
                continue
            df = pd.DataFrame(rows, columns=cols)
            n = len(df)
            coldesc = [{"name": c, "dtype": _infer_dtype(df[c])} for c in df.columns]
            inventory.append({"source": s["name"], "table": tbl, "n_rows": n,
                              "columns": coldesc})
            sig_parts.append(f'{s["name"]}.{tbl}:{n}:{",".join(df.columns)}')

            if n == 0:
                reasons.append(f"{tbl}: 0 rows")
                continue
            # Resolve the association contract via the SAME logic the stats tools use.
            oc, oerr = sc.resolve_outcome(df, None)
            gc, gerr = sc.resolve_group(df, None, oc)
            if oerr or gerr:
                ambiguous.append(tbl)
                reasons.append(f"{tbl}: {oerr or ''}{'; ' if oerr and gerr else ''}{gerr or ''}")
                continue
            # Contract resolvable — confirm it is not degenerate.
            scan = sc.group_vs_rest_scan(df, gc, oc)
            if scan["kind"] == sc.KIND_DEGENERATE:
                insufficient.append(tbl)
                reasons.append(f"{tbl}: {scan.get('reason')}")
            else:
                ready_tables.append({"table": tbl, "group_col": gc, "outcome_col": oc,
                                     "n": scan["n"]})

    signature = "|".join(sorted(sig_parts))

    if not inventory:
        return {"verdict": EMPTY, "summary": "No data sources or tables are connected yet. "
                "Upload a defect/process dataset (CSV) to begin.",
                "inventory": [], "reasons": ["no tables visible"], "signature": signature}

    inv_lines = [f'  {i["source"]}.{i["table"]}: {i["n_rows"]} rows, '
                 f'{len(i["columns"])} cols ['
                 + ", ".join(f'{c["name"]}({c["dtype"]})' for c in i["columns"]) + "]"
                 for i in inventory]
    header = "Data inventory:\n" + "\n".join(inv_lines)

    if ready_tables:
        rl = ", ".join(f'{t["table"]} (group={t["group_col"]}, outcome={t["outcome_col"]}, '
                       f'n={t["n"]})' for t in ready_tables)
        return {"verdict": READY,
                "summary": f"{header}\n\nReady for analysis: {rl}.",
                "inventory": inventory, "reasons": [], "signature": signature}

    if ambiguous:
        return {"verdict": AMBIGUOUS,
                "summary": f"{header}\n\nColumn roles are ambiguous — analysis cannot start "
                f"until they are confirmed:\n" + "\n".join(f"  - {r}" for r in reasons),
                "inventory": inventory, "reasons": reasons, "signature": signature}

    return {"verdict": INSUFFICIENT,
            "summary": f"{header}\n\nData is present but cannot support a statistical test:\n"
            + "\n".join(f"  - {r}" for r in reasons)
            + f"\n(Need a categorical group column, a binary 0/1 outcome, each group "
            f">= {cfg.stat_min_group_n} rows, and non-zero outcome variance.)",
            "inventory": inventory, "reasons": reasons, "signature": signature}
