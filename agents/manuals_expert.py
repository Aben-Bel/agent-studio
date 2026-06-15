"""Specialist: failure-mode knowledge from manuals / FMEA documents."""
from core.declare import agent


@agent(
    name="manuals_expert",
    description="Finds known failure modes and guidance in uploaded manuals / FMEA "
                "documents (RAG).",
    tools=["search_fmea", "search_docs"],
)
def manuals_expert(ctx):
    return (
        "You are a process-knowledge expert. Given a symptom, parameter, or defect, "
        "search the uploaded manuals and FMEA documents for known failure modes and "
        "recommended checks. Quote the relevant passages and cite the document. "
        "If nothing relevant is found, say so plainly."
    )
