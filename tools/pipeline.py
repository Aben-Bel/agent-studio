from pydantic import BaseModel
from core.declare import tool
from core import pipeline


class Empty(BaseModel):
    pass


@tool("process_uploads",
      "Process any uploaded documents that are not yet indexed (parse, chunk, "
      "embed into RAG). Use this if a document may have been left unprocessed.",
      Empty,
      limits="Processes already-uploaded docs only; cannot fetch URLs or re-index files already indexed.")
def process_uploads():
    done = pipeline.run_pending()
    if not done:
        return "All uploaded documents are already processed."
    ok = [d["source"] for d in done if "error" not in d]
    err = [f"{d['source']} ({d['error']})" for d in done if "error" in d]
    parts = []
    if ok:
        parts.append("Processed: " + ", ".join(ok))
    if err:
        parts.append("Failed: " + ", ".join(err))
    return " | ".join(parts)


@tool("pipeline_status",
      "Report how many uploaded documents are pending vs processed, and the "
      "stages in the processing pipeline.",
      Empty,
      limits="Reports pipeline counts/stages only; does not process documents or inspect their contents.")
def pipeline_status():
    s = pipeline.status()
    return (f"documents: {s['counts'] or 'none'} | pending: {s['pending']} | "
            f"stages: {[st['name'] for st in s['stages']]}")
