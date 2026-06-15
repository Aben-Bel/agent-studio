import os
from connectors import datastore, memory


def ingest(path, filename):
    """Tables go to the SQL store, documents go to RAG memory."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in ("csv",):
        n = datastore.load_csv(path, "jokes")
        return {"kind": "dataset", "table": "jokes", "rows": n}
    if ext in ("txt", "md"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        memory.add_document(text, filename)
        return {"kind": "document", "source": filename, "chars": len(text)}
    return {"kind": "skipped", "reason": f"unsupported type .{ext}"}
