from core.declare import stage
from connectors import memory


# Chunks + embeds the document into the vector RAG store (app.db) so it becomes
# searchable. Runs after `normalize` (higher order).
@stage("index", order=20, description="Chunk and embed the document into the vector RAG store.")
def index(doc):
    if doc.get("text", "").strip():
        memory.add_document(doc["text"], doc["source"])
    doc["indexed"] = True
    return doc
