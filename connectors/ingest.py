import os
from connectors import datastore, memory


def _read_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def ingest(path, filename):
    """Route an upload by type. Tabular data (CSV) goes to the SQL store as its
    own table; documents (PDF/TXT/MD) get chunked into RAG memory. Each CSV keeps
    its own table, so uploading many files no longer overwrites one another."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    stem = os.path.splitext(os.path.basename(filename))[0]

    if ext == "csv":
        info = datastore.load_csv(path, table=stem)
        return {"kind": "dataset", "table": info["table"],
                "rows": info["rows"], "source": info["source"]}

    if ext == "pdf":
        text = _read_pdf(path)
        memory.add_document(text, filename)
        return {"kind": "document", "source": filename, "chars": len(text)}

    if ext in ("txt", "md"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        memory.add_document(text, filename)
        return {"kind": "document", "source": filename, "chars": len(text)}

    return {"kind": "skipped", "reason": f"unsupported type .{ext}"}
