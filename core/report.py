"""Assemble a structured, replicable report from an investigation's audit trail.

Exporters (Markdown, LaTeX/PDF, ...) all consume this one neutral shape, so a new
output format is just a function `report -> bytes` and never re-walks the raw
event log. The report is "replicable" by construction: every conclusion carries
the exact agents, tools, and tool arguments (the queries) that produced it, so a
reader can reproduce the analysis."""
from datetime import datetime, timezone

from . import runs
from connectors import datastore, memory


def _clip(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def build_report(chat_id, title=None):
    """Walk the persisted trace into turns. Each turn:
        question, conclusion, agents[], evidence[] (agent/tool/args/result).
    Pure read of the audit trail - works offline and needs no model call."""
    steps = runs.get_run(chat_id).get("steps", [])

    turns, cur = [], None
    pending = {}   # tool_call_id -> evidence row awaiting its result
    for s in steps:
        ty, d = s.get("type"), s.get("data", {})
        if ty == "user_message":
            cur = {"question": d.get("text", ""), "conclusion": "",
                   "agents": [], "evidence": []}
            turns.append(cur)
            pending = {}
            continue
        if cur is None:
            cur = {"question": "", "conclusion": "", "agents": [], "evidence": []}
            turns.append(cur)
        scope = d.get("agent_scope") or "orchestrator"
        if ty == "agent_switch" and d.get("role") in ("working", "recruited"):
            a = d.get("agent")
            if a and a not in cur["agents"]:
                cur["agents"].append(a)
        elif ty == "tool_call" and d.get("name") not in ("ask_human",):
            row = {"agent": scope, "kind": d.get("kind", "tool"), "tool": d.get("name", ""),
                   "args": d.get("args") or {}, "result": ""}
            cur["evidence"].append(row)
            # tool_call/tool_result aren't id-paired in the stream; match the next
            # result for the same tool name within this turn.
            pending.setdefault(d.get("name", ""), []).append(row)
        elif ty == "tool_result":
            row_list = pending.get(d.get("name", ""))
            if row_list:
                row_list.pop(0)["result"] = d.get("result", "")
        elif ty == "final" and not d.get("depth"):
            cur["conclusion"] = d.get("message", "")

    # Only keep turns that actually concluded something worth reporting.
    turns = [t for t in turns if t["question"] or t["conclusion"]]

    sources = []
    try:
        for s in datastore.list_sources():
            sources.append({"name": s["name"], "dialect": s.get("dialect", ""),
                            "tables": s.get("tables", [])})
    except Exception:
        pass
    documents = []
    try:
        for dd in memory.list_documents():
            documents.append({"source": dd["source"], "chars": dd.get("chars", 0)})
    except Exception:
        pass

    headline = ""
    for t in reversed(turns):
        if t["conclusion"]:
            headline = t["conclusion"]
            break

    return {
        "chat_id": chat_id,
        "title": title or "Yield Root-Cause Analysis",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "headline": headline,
        "turns": turns,
        "data_sources": sources,
        "documents": documents,
    }


def evidence_line(e, arg_len=160, res_len=240):
    """One human line summarising a piece of evidence: agent, tool, the call, result."""
    args = ", ".join(f"{k}={_clip(v, 60)}" for k, v in (e.get("args") or {}).items())
    call = f"{e.get('tool', '')}({_clip(args, arg_len)})"
    return e.get("agent", ""), call, _clip(e.get("result", ""), res_len)
