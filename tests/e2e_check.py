"""End-to-end backend checks for the Yield Analysis RCA platform.
Run: MOCK_LLM=1 DB_PATH=/tmp/rca_e2e.db ./env/bin/python -m tests.test_e2e
"""
import os, tempfile

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DB_PATH", "/tmp/rca_e2e.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])

from core.discovery import discover
from core.registry import TOOLS
from core import orchestrator, model, runs, pipeline
from connectors import datastore, ingest, memory

discover()
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  -- {detail}" if detail else ""))


def _tmp_csv(text):
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.write(fd, text.encode()); os.close(fd); return p


# ---------------------------------------------------------------- data layer
a = _tmp_csv("setup,defect\nA,1\nB,0\n")
b = _tmp_csv("city,pop\nBerlin,3000000\nParis,2000000\n")
ra = ingest.ingest(a, "lot_alpha.csv")
ingest.ingest(b, "cities.csv")
tables = {s["name"]: s["tables"] for s in datastore.list_sources()}["local"]
check("multi-CSV: distinct tables, no overwrite",
      "lot_alpha" in tables and "cities" in tables, str(tables))

ext_db = tempfile.mktemp(suffix=".db")
info = datastore.connect_db(f"sqlite:///{ext_db}", "warehouse")
check("connect-db: external source registered + listed",
      info["name"] == "warehouse" and "warehouse" in [s["name"] for s in datastore.list_sources()])
check("db-url: postgres:// normalized",
      datastore._normalize_url("postgres://u:p@h/d") == "postgresql://u:p@h/d")

qd = TOOLS.get("query_data").fn
check("query_data: reads rows", "Berlin" in qd("select city from cities", "local"))
check("query_data: refuses writes", "read-only" in qd("drop table cities", "local").lower())

# ---------------------------------------------------------------- RCA tools
datastore.load_csv("data/sources/semiconductor_wafer_defect_dataset.csv", "wafer_defects")
corr = TOOLS.get("correlate_params_vs_yield").fn("wafer_defects", "defect_label")
check("RCA correlate: real correlation over wafer data",
      "Strongest driver" in corr and "r=" in corr, corr.splitlines()[0] if corr else "")

# FMEA / RAG over the seeded manual
with open("data/sources/fab_process_manual.md") as f:
    pipeline.add_upload("fab_process_manual.md", f.read())
pipeline.run_pending()
fmea = TOOLS.get("search_fmea").fn("etch temperature critical dimension")
check("RCA search_fmea: RAG returns manual passages", "etch" in fmea.lower(), fmea[:60])

check("RCA stubs: registered + honest", "[not implemented yet]" in TOOLS.get("query_fdc_timeseries").fn("L1"))

# ---------------------------------------------------------------- discovery + contracts
caps = orchestrator.capabilities()
check("discovery: subfolder tools/rca/* loaded",
      "correlate_params_vs_yield" in [t["name"] for t in caps["tools"]])
check("contracts: tools carry owner/version",
      all("owner" in t and "version" in t for t in caps["tools"]))
check("capabilities: mcp + stages present",
      "mcp" in caps and "stages" in caps and len(caps["stages"]) >= 1)

# --------------------------------------------------- stateful orchestrator + audit
evs = list(orchestrator.start_or_resume("inv-1", "rca_assistant", "why is yield dropping on lithography"))
types = [e["type"] for e in evs]
check("session: streams a tool-using investigation",
      types[0] == "agent_switch" and "tool_call" in types and types[-1] == "final", str(types))

# audit trail persisted (in DB, separate read)
trail = runs.get_run("inv-1")
check("audit: every step persisted to app.db", len(trail["steps"]) >= 3, f"{len(trail['steps'])} steps")
check("audit: run listed with status", any(r["chat_id"] == "inv-1" for r in runs.list_runs()))

# memory across turns
list(orchestrator.start_or_resume("inv-1", "rca_assistant", "and on deposition?"))
st = orchestrator.session_state("inv-1")
check("session: remembers across turns",
      sum(1 for m in st["transcript"] if m["role"] == "user") == 2, str(st["transcript"]))

# --------------------------------------------------- human-in-the-loop
calls = {"n": 0}
real = model.complete
def fake_hitl(msgs, funcs, system):
    calls["n"] += 1
    if calls["n"] == 1:
        return model.Resp(tool_calls=[{"id": "h1", "name": "ask_human",
                                       "arguments": {"question": "Which lot?"}}])
    return model.Resp(content="Analyzed lot 42.")
model.complete = fake_hitl
try:
    e1 = list(orchestrator.start_or_resume("inv-h", "rca_assistant", "investigate"))
    check("hitl: pauses with needs_human", e1[-1]["type"] == "needs_human", str([e["type"] for e in e1]))
    check("hitl: surfaces question",
          orchestrator.session_state("inv-h")["pending_question"] == "Which lot?")
    e2 = list(orchestrator.start_or_resume("inv-h", "rca_assistant", "lot 42"))
    f2 = next((e for e in e2 if e["type"] == "final"), None)
    check("hitl: resumes to final with the answer", bool(f2 and "42" in f2["data"]["message"]))
finally:
    model.complete = real

# --------------------------------------------------- mid-run context catch-up
calls2 = {"n": 0}
def fake_ctx(msgs, funcs, system):
    calls2["n"] += 1
    if calls2["n"] == 1:
        orchestrator.add_context("inv-c", "Note: only consider the etch chamber.")
        return model.Resp(tool_calls=[{"id": "t1", "name": "search_fmea",
                                       "arguments": {"query": "etch"}}])
    return model.Resp(content="done")
model.complete = fake_ctx
try:
    ec = list(orchestrator.start_or_resume("inv-c", "rca_assistant", "investigate"))
    tc = [e["type"] for e in ec]
    check("context: mid-run catch-up without breaking",
          "context_added" in tc and tc[-1] == "final", str(tc))
finally:
    model.complete = real

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL BACKEND CHECKS PASSED")
