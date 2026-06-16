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


# Tools/skills whose results are NOT citable "evidence" for a data claim: data discovery,
# IO, human prompts, and ADVISORY MATCHING (role/persona matchers read no row data and
# run no analysis — citing them as proof of a finding is misleading). Listing them just
# adds noise, or worse, dresses up advice as evidence.
_NON_EVIDENCE_TOOLS = {"ask_human", "list_data_sources", "load_uploaded_csv",
                       "prepare_download", "yield_persona_support"}


def turn_references(chat_id):
    """The citable evidence for the LATEST concluded turn, shaped for the UI's
    reference modal. Each reference is what a normal user needs to verify a claim:
      {n, agent, tool, call, args, result, sources}
    where `sources` is the table.column(s) / document(s) the call actually touched.
    Pure read of the audit trail — reproducible, no model call."""
    report = build_report(chat_id)
    turns = report.get("turns") or []
    if not turns:
        return []
    evidence = turns[-1].get("evidence") or []
    refs = []
    seen = set()
    for e in evidence:
        if e.get("tool") in _NON_EVIDENCE_TOOLS:
            continue
        result = (e.get("result") or "").strip()
        if not result:
            continue
        # Dedupe identical calls (the same tool+args+result run by two agents in
        # parallel is ONE piece of evidence, not two references).
        key = (e.get("tool", ""), str(e.get("args") or {}), result)
        if key in seen:
            continue
        seen.add(key)
        agent, call, _ = evidence_line(e, arg_len=200, res_len=10_000)
        refs.append({
            "n": len(refs) + 1,
            "agent": agent,
            "tool": e.get("tool", ""),
            "call": call,
            "args": e.get("args") or {},
            "result": e.get("result", ""),
            "sources": _sources_touched(e),
        })
    return refs


def _salient_tokens(text):
    """The verifiable tokens in a piece of text: numbers (incl. decimals, %, sci-notation)
    and multi-char identifiers (column/step/table names). These are what a claim and its
    backing tool result must SHARE for the claim to be 'supported by' that result.
    Common words are ignored so a match means a real data overlap, not English overlap."""
    import re
    low = (text or "").lower()
    nums = re.findall(r'\d+(?:[.,]\d+)?(?:e[-+]?\d+)?%?', low)
    # A number is a STRONG fingerprint only if it is distinctive: a decimal, a p-value
    # (sci-notation), a percentage, or a 3+ digit integer (e.g. 5000). Bare small
    # integers (1-2 digits like '5 steps', 'LIMIT 5') match by coincidence — drop them.
    norm_nums = set()
    for tok in nums:
        t = tok.rstrip("%")
        digits = t.replace(",", "").replace(".", "")
        if "." in t or "e" in t or tok.endswith("%") or len(digits) >= 3:
            norm_nums.add(t)
    idents = set(re.findall(r'[a-z_]{4,}', low)) - _STOPWORDS
    return norm_nums, idents


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are", "was",
    "were", "which", "step", "steps", "data", "table", "value", "values", "test",
    "result", "results", "found", "show", "shows", "there", "their", "than", "then",
    "rate", "rates", "after", "across", "each", "most", "more", "less", "they", "them",
    "associated", "association", "significant", "analysis", "defect", "defects", "yield",
    "overall", "process", "parameter", "parameters", "column", "columns", "between",
}


def cite_conclusion(text, references):
    """Tie each sentence of `text` to the tool-result references that actually support it,
    by salient-token overlap (numbers + identifiers shared between the sentence and a
    reference's result). DETERMINISTIC — no model call, so a citation only appears where
    the data really backs the words.

    Returns (annotated_text, used_references):
      * annotated_text  — the conclusion with a superscript marker (e.g. '…lift +0.046¹')
        appended to each sentence that has supporting evidence.
      * used_references — only the references actually cited, renumbered 1..k, so the UI
        shows evidence the answer USED, not every tool that ran.
    """
    import re
    if not text or not references:
        return text, []

    # Pre-compute each reference's salient tokens from its (tool args + result).
    ref_tokens = []
    for r in references:
        blob = (r.get("call", "") + " " + str(r.get("result", "")) + " "
                + str(r.get("sources", "")))
        ref_tokens.append(_salient_tokens(blob))

    # Identifiers shared by MOST references (e.g. the queried table name 'wafer_defects',
    # present in every query) carry no discriminating signal — a claim mentioning them
    # would match everything. Treat them as stopwords for matching.
    from collections import Counter
    idf = Counter()
    for _, idents in ref_tokens:
        for w in idents:
            idf[w] += 1
    ubiquitous = {w for w, c in idf.items() if c >= max(2, len(references) * 0.6)}
    ref_tokens = [(nums, idents - ubiquitous) for nums, idents in ref_tokens]

    # Split into sentences while keeping the trailing punctuation/whitespace.
    parts = re.split(r'(?<=[.!?])(\s+)', text)
    out = []
    used_order = []   # original ref index in first-cited order

    i = 0
    while i < len(parts):
        sentence = parts[i]
        tail = parts[i + 1] if i + 1 < len(parts) else ""
        s_nums, s_idents = _salient_tokens(sentence)
        if s_nums or s_idents:
            hits = []
            for idx, (r_nums, r_idents) in enumerate(ref_tokens):
                # A reference supports the sentence if they share a salient NUMBER, or
                # at least two identifiers (one shared word is too weak).
                if (s_nums & r_nums) or len(s_idents & r_idents) >= 2:
                    hits.append(idx)
            if hits:
                # Bracketed markers like [1][2][17] — readable even when several stack on
                # one sentence (unicode superscripts ran together into an unreadable blur).
                marks = ""
                for idx in hits:
                    if idx not in used_order:
                        used_order.append(idx)
                    marks += f"[{used_order.index(idx) + 1}]"
                # place the marker before the sentence's closing punctuation, with a thin
                # space so it doesn't touch the last word
                m = re.search(r'[.!?]+$', sentence.rstrip())
                if m:
                    cut = sentence.rstrip()
                    sentence = cut[:m.start()] + " " + marks + cut[m.start():] + \
                        sentence[len(sentence.rstrip()):]
                else:
                    sentence = sentence + " " + marks
        out.append(sentence)
        if tail:
            out.append(tail)
        i += 2

    if not used_order:
        return text, []

    used_references = []
    for new_n, idx in enumerate(used_order, start=1):
        ref = dict(references[idx])
        ref["n"] = new_n
        used_references.append(ref)
    return "".join(out), used_references


def _sources_touched(e):
    """Best-effort: the table / column / document names a piece of evidence references,
    pulled from its args + result so the modal can say 'from wafer_defects.process_step'."""
    hits = []
    args = e.get("args") or {}
    for key in ("table", "source", "group_col", "outcome_col", "column", "columns",
                "query", "sql"):
        v = args.get(key)
        if v:
            hits.append(str(v))
    return _clip(", ".join(dict.fromkeys(hits)), 200) if hits else ""
