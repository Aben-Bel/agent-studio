"""Markdown report exporter. Renders the professional document model (executive
summary, coherent sections, data tables, recommendations). Always available."""
from core.declare import exporter


def _table(t):
    cols = t["columns"]
    rows = t["rows"]
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


@exporter("report_md", "Report (Markdown)",
          description="Professional written report: executive summary, findings with "
                      "data tables, and recommendations. Opens anywhere.",
          extension="md", media_type="text/markdown")
def report_md(doc):
    L = [f"# {doc['title']}", "", f"*{doc.get('subtitle', '')} — {doc['generated']}*", ""]

    if doc.get("executive_summary"):
        L += ["## Executive summary", "", doc["executive_summary"], ""]

    for sec in doc.get("sections", []):
        L += [f"## {sec['heading']}", ""]
        for b in sec.get("bullets", []):
            L.append(f"- {b}")
        if sec.get("bullets"):
            L.append("")
        if sec.get("table"):
            L += [_table(sec["table"]), ""]

    if doc.get("recommendations"):
        L += ["## Recommendations", ""]
        for i, r in enumerate(doc["recommendations"], 1):
            L.append(f"{i}. {r}")
        L.append("")

    if doc.get("data_sources"):
        L += ["---", "", "*Data sources: " + ", ".join(doc["data_sources"]) + "*", ""]

    return ("\n".join(L)).encode("utf-8")
