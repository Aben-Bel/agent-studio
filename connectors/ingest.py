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
    """Process an upload: extract its text, RECORD it as a pending document, then
    run the pipeline (normalize -> index -> ...) so it becomes RAG-searchable. CSVs
    additionally load into their own SQL table. The recording + sweep means a doc
    is never silently lost: process_uploads / run_pending re-processes leftovers."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in ("csv", "pdf", "txt", "md"):
        return {"kind": "skipped", "reason": f"unsupported type .{ext}"}

    text = _extract(path, ext)
    if text.strip():
        pipeline.add_upload(filename, text)          # status=pending

    if ext == "csv":
        info = datastore.load_csv(path, table=os.path.splitext(os.path.basename(filename))[0])
        result = {"kind": "dataset", "table": info["table"], "rows": info["rows"]}
    else:
        result = {"kind": "document", "source": filename, "chars": len(text)}

    pipeline.run_pending()                            # process now (+ sweep any leftovers)
    return result
