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
  "title": "report title - a NOUN PHRASE label, max 8 words, NOT a sentence",
  "subtitle": "one-line scope (e.g. lot / process / time window)",
  "executive_summary": "2-3 sentences: the answer and the single most likely root cause, up front",
  "sections": [
    {
      "heading": "section heading - max 5 words, a label not a sentence",
      "bullets": ["ONE idea, max 12 words, citing a real value and its source", "..."],
      "table": {"columns": ["Col", "Col"], "rows": [["v", "v"], ["v", "v"]]}
    }
  ],
  "recommendations": ["one actionable next step, max 12 words", "..."],
  "data_sources": ["table.column or document.pdf actually used", "..."]
}
SLIDE-DESIGN RULES (this becomes a slide deck - one idea per slide, no text walls):
- Title and every heading are SHORT LABELS (noun phrases), never a sentence and never
  a question. Do NOT start a title with "To answer", "I need", "How to", etc.
- Each bullet is ONE idea, at most ~12 words. Split a long finding into several bullets.
  Never paste an analyst's full sentence as a single bullet.
- 3-5 sections max, at most 5 bullets per section. Prefer a small table to a wall of text.
- Each "table" is OPTIONAL - include it only when the data is tabular, else omit the key.
- Use ONLY numbers/identifiers present in the verified data. No filler, no emojis,
  no chat references, no markdown headings inside text.'''


# Slide chrome (frame titles the template emits) per language, so a German deck is
# German end-to-end, not English headings around German bullets.
_LABELS = {
    "en": {"summary": "Executive summary", "recommendations": "Recommendations",
           "data_sources": "Data sources", "grounded": "Grounded in verified data:",
           "subtitle": "Root-Cause Analysis"},
    "de": {"summary": "Zusammenfassung", "recommendations": "Empfehlungen",
           "data_sources": "Datenquellen", "grounded": "Auf verifizierten Daten basierend:",
           "subtitle": "Ursachenanalyse"},
}


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


def build_document(chat_id, title=None, lang="en"):
    """Return the professional document model for a chat. LLM-authored when online
    and grounded in verified data; a deterministic structured fallback otherwise.
    `lang` makes the deck's prose AND its frame chrome come out in that language."""
    raw = report.build_report(chat_id, title=title)
    verified = _verified_data(raw)
    labels = _LABELS.get(lang, _LABELS["en"])

    sysprompt = "You produce precise, well-structured engineering reports as strict JSON."
    if lang != "en":
        name = model.LANG_NAME.get(lang, "English")
        sysprompt += (f" Write ALL human-readable text (title, headings, summary, bullets, "
                      f"recommendations) in {name}. Keep table/column names, identifiers, "
                      "numbers, and units exactly as in the data.")

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
                [], sysprompt, max_tokens=2200)
            doc = _parse(r.content)
        except Exception:
            doc = None

    if not doc:
        doc = _fallback(raw, labels)

    # Ground the metadata regardless of source.
    doc.setdefault("title", raw["title"])
    doc.setdefault("subtitle", labels["subtitle"])
    doc.setdefault("recommendations", [])
    if not doc.get("data_sources"):
        doc["data_sources"] = [f"{s['name']}.{tb}" for s in raw["data_sources"] for tb in s["tables"]] \
            or [d["source"] for d in raw["documents"]]
    doc["generated"] = raw["generated"]
    doc["chat_id"] = chat_id
    doc["lang"] = lang
    doc["labels"] = labels          # frame-title chrome the exporter renders
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


def _heading_from(text, fallback="Findings"):
    """A short LABEL from a question/sentence: first clause, no markdown, clamped -
    so the fallback deck gets real headings, not a pasted sentence."""
    import re as _re
    s = " ".join(str(text or "").split())
    s = _re.sub(r"\*\*(.+?)\*\*", r"\1", s).replace("**", "").replace("`", "")
    s = _re.split(r"[.?!:]", s, maxsplit=1)[0].strip().rstrip("?.!:")
    if not s:
        return fallback
    words = s.split()
    return " ".join(words[:8]) + ("..." if len(words) > 8 else "")


def _bulletize(text):
    """Split one analyst conclusion into short, slide-friendly bullets instead of a
    single wall-of-text bullet (the cause of the ugly deck)."""
    import re as _re
    s = " ".join(str(text or "").split())
    if not s:
        return []
    # Split on sentence/clause boundaries and bullet/dash separators the analyst uses.
    parts = _re.split(r"(?<=[.;])\s+|\s+[-–—]\s+|\s*•\s*", s)
    out = []
    for p in parts:
        p = p.strip().strip("-–—• ").rstrip(".")
        if len(p) > 2:
            out.append(p)
    return out[:5] or [s[:160]]


def _fallback(raw, labels):
    """Offline / model-failure path: still a structured, slide-friendly document -
    short headings and bulletized findings, never a pasted transcript."""
    sections = []
    for t in raw["turns"]:
        if not t.get("conclusion"):
            continue
        sections.append({"heading": _heading_from(t.get("question"), labels.get("summary", "Findings")),
                         "bullets": _bulletize(t["conclusion"]), "table": None})
    return {"title": raw["title"], "subtitle": labels["subtitle"],
            "executive_summary": raw.get("headline") or "",
            "sections": sections, "recommendations": [], "data_sources": []}
