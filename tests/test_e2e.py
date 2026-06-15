"""End-to-end backend checks for the new data layer + stateful orchestrator.
Run: MOCK_LLM=1 ./env/bin/python -m tests.test_e2e
"""
import os, tempfile

os.environ.setdefault("MOCK_LLM", "1")

from core.discovery import discover
from core.registry import TOOLS, MCP
from core import orchestrator, model
from connectors import datastore, ingest, memory

discover()
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  -- {detail}" if detail else ""))


def _tmp_csv(text):
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.write(fd, text.encode()); os.close(fd); return p


def _minimal_pdf(body_text):
    """Build a tiny but valid PDF (correct xref offsets) containing body_text."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\nBT /F1 18 Tf 20 100 Td (%s) Tj ET\nendstream"
        % (len(body_text) + 26, body_text.encode()),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, o)
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objs) + 1, xref_pos)
    fd, p = tempfile.mkstemp(suffix=".pdf")
    os.write(fd, out); os.close(fd); return p


# ---------------------------------------------------------------- data layer
# 1) Multiple CSVs -> distinct tables (no overwrite)
a = _tmp_csv("setup,punchline\nQ1,A1\nQ2,A2\n")
b = _tmp_csv("city,pop\nBerlin,3000000\nParis,2000000\n")
ra = ingest.ingest(a, "alpha_jokes.csv")
rb = ingest.ingest(b, "cities.csv")
tables = {s["name"]: s["tables"] for s in datastore.list_sources()}["local"]
check("multi-CSV: alpha table created", ra["table"] == "alpha_jokes" and ra["rows"] == 2)
check("multi-CSV: cities table created", rb["table"] == "cities" and rb["rows"] == 2)
check("multi-CSV: both coexist (no overwrite)",
      "alpha_jokes" in tables and "cities" in tables, str(tables))

# 2) Connect a DB by URL (use a separate sqlite file = a real external 'source')
ext_db = tempfile.mktemp(suffix=".db")
info = datastore.connect_db(f"sqlite:///{ext_db}", "warehouse")
check("connect-db: registered external source", info["name"] == "warehouse", str(info))
datastore.load_csv(b, table="cities", source="warehouse")
names = [s["name"] for s in datastore.list_sources()]
check("connect-db: shows in list_sources", "warehouse" in names, str(names))

# 3) postgres:// URL normalization (don't connect — just validate it parses/normalizes)
norm = datastore._normalize_url("postgres://u:p@host:5432/db")
check("db-url: postgres:// normalized to postgresql://",
      norm == "postgresql://u:p@host:5432/db", norm)

# 4) query_data tool runs read-only SQL and refuses writes
qd = TOOLS.get("query_data").fn
out = qd("select city, pop from cities order by city", "warehouse")
check("query_data: returns rows from connected source", "Berlin" in out and "Paris" in out, out)
refused = qd("drop table cities", "warehouse")
check("query_data: refuses non-SELECT", "read-only" in refused.lower(), refused)

# 5) PDF ingest -> document text extracted into RAG memory
pdf = _minimal_pdf("Knock knock who is there")
rp = ingest.ingest(pdf, "manual.pdf")
check("pdf: routed to document", rp["kind"] == "document", str(rp))
check("pdf: text extracted (chars>0)", rp.get("chars", 0) > 0, str(rp))
hits = memory.search("knock", k=3)
check("pdf: extracted text is searchable", any("knock" in h.lower() for h in hits), str(hits))

# 6) MCP discovered as a capability category
caps = orchestrator.capabilities()
check("capabilities: mcp category present",
      "mcp" in caps and any(m["name"] == "filesystem" for m in caps["mcp"]), str(caps.get("mcp")))
check("capabilities: subfolder tool 'echo' present",
      any(t["name"] == "echo" for t in caps["tools"]))

# ---------------------------------------------------- stateful orchestrator
# 7) Joker flow via stateful session produces a real joke
datastore.load_csv("data/sources/jokes.csv", "jokes")   # ensure jokes table
evs = list(orchestrator.start_or_resume("chat-1", "joker", "tell me a joke"))
types = [e["type"] for e in evs]
final = next((e for e in evs if e["type"] == "final"), None)
check("session: emits agent_switch first", types[0] == "agent_switch", str(types))
check("session: calls a tool", "tool_call" in types, str(types))
check("session: ends with final", types[-1] == "final", str(types))
check("session: final has joke text", bool(final and final["data"]["message"].strip()),
      final["data"]["message"] if final else "no final")

# 8) Memory across turns: second turn keeps the same session/history
evs2 = list(orchestrator.start_or_resume("chat-1", "joker", "another one"))
st = orchestrator.session_state("chat-1")
user_turns = sum(1 for m in st["transcript"] if m["role"] == "user")
check("session: remembers across turns (2 user turns)", user_turns == 2, str(st["transcript"]))
check("session: status done after final", st["status"] == "done", st["status"])

# 9) Human-in-the-loop: pause on ask_human, then resume with the answer
calls = {"n": 0}
real_complete = model.complete
def fake_complete(msgs, funcs, system):
    calls["n"] += 1
    if calls["n"] == 1:
        return model.Resp(tool_calls=[{"id": "h1", "name": "ask_human",
                                       "arguments": {"question": "What's your name?"}}])
    return model.Resp(content="Nice to meet you, Sam!")
model.complete = fake_complete
try:
    from core.declare import agent as _agent_dec
    from core.registry import AGENTS
    from core.declare import AgentDecl
    AGENTS.register("hitl")(AgentDecl("hitl", "asks the human", lambda c: "be helpful",
                                      ["ask_human"]))
    e1 = list(orchestrator.start_or_resume("chat-hitl", "hitl", "hi"))
    t1 = [e["type"] for e in e1]
    check("hitl: pauses with needs_human", t1[-1] == "needs_human", str(t1))
    check("hitl: no final before answer", "final" not in t1, str(t1))
    paused = orchestrator.session_state("chat-hitl")
    check("hitl: status awaiting_human", paused["status"] == "awaiting_human", paused["status"])
    check("hitl: surfaces pending question",
          paused["pending_question"] == "What's your name?", str(paused.get("pending_question")))
    e2 = list(orchestrator.start_or_resume("chat-hitl", "hitl", "Sam"))
    t2 = [e["type"] for e in e2]
    final2 = next((e for e in e2 if e["type"] == "final"), None)
    check("hitl: resumes to final after answer", t2[-1] == "final", str(t2))
    check("hitl: final reflects the human answer",
          bool(final2 and "Sam" in final2["data"]["message"]),
          final2["data"]["message"] if final2 else "none")
finally:
    model.complete = real_complete

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL BACKEND CHECKS PASSED")
