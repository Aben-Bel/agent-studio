"""RCA tool: search FMEA / failure-mode knowledge and equipment manuals.

REAL tool — runs over whatever manuals/FMEA documents have been uploaded (they
are chunked + embedded by the ingestion pipeline). Returns the most relevant
passages so the agent can cite known failure modes for a symptom."""
from pydantic import BaseModel
from core.declare import tool
from connectors import memory


class FmeaArgs(BaseModel):
    query: str           # a symptom, defect signature, or parameter name


@tool("search_fmea",
      "Search uploaded FMEA / failure-mode knowledge and equipment manuals for "
      "passages relevant to a defect symptom or parameter.",
      FmeaArgs, owner="rca-core", tags=["rag", "knowledge"])
def search_fmea(query):
    hits = memory.search(query, k=4)
    if not hits:
        return ("No FMEA/manual passages found. Upload failure-mode docs or "
                "equipment manuals to enable this.")
    return "Relevant failure-mode / manual passages:\n\n" + "\n\n---\n\n".join(hits)
