import os
from connectors import datastore
from core import pipeline


def _read_pdf(path):
    from pypdf import PdfReader
    return "\n\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


def _extract(path, ext):
    if ext == "pdf":
        return _read_pdf(path)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def ingest(path, filename):
    """Route an upload by type:
      - CSV  -> its own queryable SQL TABLE (not a document).
      - PDF/TXT/MD -> a searchable DOCUMENT in the RAG store (via the pipeline).
    A CSV is structured data you query, not prose you search, so it is never
    indexed as a document."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    stem = os.path.splitext(os.path.basename(filename))[0]

    if ext == "csv":
        info = datastore.load_csv(path, table=stem)
        return {"kind": "dataset", "table": info["table"], "rows": info["rows"]}

    if ext in ("pdf", "txt", "md"):
        text = _extract(path, ext)
        if text.strip():
            pipeline.add_upload(filename, text)
            pipeline.run_pending()
        return {"kind": "document", "source": filename, "chars": len(text)}

    return {"kind": "skipped", "reason": f"unsupported type .{ext}"}
