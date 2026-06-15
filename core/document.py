"""Author a PROFESSIONAL, structured document from an investigation.

The deliverable is documentation / a presentation - NOT a chat transcript. The
audit trail gives us the verified findings and the exact data behind them; an LLM
turns that into a coherent, concise executive document, grounded STRICTLY in the
provided values (it may not invent a number, lot id, cause, or percentage). Every
exporter renders this one model, so Markdown and the slide deck stay consistent.
"""
import json

from . import model, report
from .config import cfg

# The shape we ask the model for. Kept flat and strict so it renders cleanly to
# both Markdown and Beamer with no post-processing.
_SCHEMA = '''Return ONLY valid JSON (no code fences, no prose around it):
{
  "title": "short, specific report title",
  "subtitle": "one-line scope (e.g. lot / process / time window)",
  "executive_summary": "2-4 sentences: the answer and the single most likely root cause, up front",
  "sections": [
    {
      "heading": "short section heading",
      "bullets": ["concise finding citing a real value and its source", "..."],
      "table": {"columns": ["Col", "Col"], "rows": [["v", "v"], ["v", "v"]]}
    }
  ],
  "recommendations": ["specific, actionable next step", "..."],
  "data_sources": ["table.column or document.pdf actually used", "..."]
}
Rules: 3-5 sections max. Each "table" is OPTIONAL - include it only when the data
is tabular, otherwise omit the key. Use ONLY numbers/identifiers present in the
verified data. Be concise and coherent. No filler, no emojis, no chat references.'''


def _verified_data(raw):
    """The ONLY facts the author may cite: each analyst conclusion plus the exact
    tool call and its real result (the queries and their returned rows)."""
    out = []
    for t in raw["turns"]:
        if t.get("question"):
            out.append(f"QUESTION: {t['question']}")
        if t.get("conclusion"):
            out.append(f"ANALYST CONCLUSION: {t['conclusion']}")
        for e in t.get("evidence", []):
            _, call, res = report.evidence_line(e, arg_len=220, res_len=700)
            out.append(f"DATA  {call}\n  -> {res}")
        out.append("")
    return "\n".join(out).strip()


def build_document(chat_id, title=None):
    """Return the professional document model for a chat. LLM-authored when online
    and grounded in verified data; a deterministic structured fallback otherwise."""
    raw = report.build_report(chat_id, title=title)
    verified = _verified_data(raw)

    doc = None
    if not cfg.mock_llm and verified:
        try:
            r = model.complete(
                [{"role": "user", "content":
                  "You are writing a professional root-cause-analysis report for "
                  "semiconductor yield engineers and their managers. The reader did "
                  "NOT see the chat - this must stand alone as documentation.\n\n"
                  "VERIFIED DATA (the only facts you may use; do not invent any value, "
                  f"lot id, percentage, or cause not present here):\n{verified}\n\n"
                  "Write a concise, coherent executive document. Lead with the answer, "
                  "group findings logically, format tabular data as tables, and cite the "
                  f"source (table.column or document) for every quantitative claim.\n\n{_SCHEMA}"}],
                [], "You produce precise, well-structured engineering reports as strict JSON.",
                max_tokens=2200)
            doc = _parse(r.content)
        except Exception:
            doc = None

    if not doc:
        doc = _fallback(raw)

    # Ground the metadata regardless of source.
    doc.setdefault("title", raw["title"])
    doc.setdefault("subtitle", "Root-Cause Analysis")
    doc.setdefault("recommendations", [])
    if not doc.get("data_sources"):
        doc["data_sources"] = [f"{s['name']}.{tb}" for s in raw["data_sources"] for tb in s["tables"]] \
            or [d["source"] for d in raw["documents"]]
    doc["generated"] = raw["generated"]
    doc["chat_id"] = chat_id
    doc["empty"] = not (doc.get("sections") or doc.get("executive_summary"))
    return doc


def _parse(text):
    s = (text or "").strip()
    if "```" in s:                                   # strip ```json fences if present
        parts = s.split("```")
        s = parts[1] if len(parts) > 1 else s
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s[s.find("{"): s.rfind("}") + 1]
    d = json.loads(s)
    if not isinstance(d, dict) or "sections" not in d:
        raise ValueError("document JSON missing sections")
    # Normalise: drop malformed sections/tables defensively.
    secs = []
    for sec in d.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        tb = sec.get("table")
        if not (isinstance(tb, dict) and tb.get("columns") and tb.get("rows")):
            sec["table"] = None
        sec["bullets"] = [str(b) for b in (sec.get("bullets") or []) if str(b).strip()]
        sec["heading"] = str(sec.get("heading") or "").strip() or "Findings"
        secs.append(sec)
    d["sections"] = secs
    d["recommendations"] = [str(r) for r in (d.get("recommendations") or []) if str(r).strip()]
    return d


def _fallback(raw):
    """Offline / model-failure path: still a structured document, not a transcript."""
    sections = []
    for t in raw["turns"]:
        bullets = [t["conclusion"]] if t.get("conclusion") else []
        sections.append({"heading": (t.get("question") or "Findings")[:80],
                         "bullets": bullets, "table": None})
    return {"title": raw["title"], "subtitle": "Root-Cause Analysis",
            "executive_summary": raw.get("headline") or "See findings below.",
            "sections": sections, "recommendations": [], "data_sources": []}
