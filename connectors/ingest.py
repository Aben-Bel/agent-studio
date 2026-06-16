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

    if ext == "json":
        return _ingest_json(path, filename, stem)

    if ext in ("pdf", "txt", "md"):
        text = _extract(path, ext)
        if text.strip():
            pipeline.add_upload(filename, text)
            pipeline.run_pending()
        return {"kind": "document", "source": filename, "chars": len(text)}

    return {"kind": "skipped", "reason": f"unsupported type .{ext}"}


def _ingest_json(path, filename, stem):
    """A JSON array-of-objects is tabular -> load it as a queryable SQL table
    (like a CSV). Any other JSON shape is prose-ish config/metadata -> index it as
    a searchable document so it is at least usable. Never silently skipped."""
    import json
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception as e:
        return {"kind": "error", "reason": f"invalid JSON: {e}"}

    # records = a list of flat dicts -> a table.
    records = data if isinstance(data, list) else None
    if records and all(isinstance(r, dict) for r in records) and records:
        info = datastore.load_records(records, table=stem)
        return {"kind": "dataset", "table": info["table"], "rows": info["rows"]}

    # Otherwise keep it as a readable document (pretty-printed) in the RAG store.
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if text.strip():
        pipeline.add_upload(filename, text)
        pipeline.run_pending()
    return {"kind": "document", "source": filename, "chars": len(text)}
