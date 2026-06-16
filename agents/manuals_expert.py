"""Specialist: failure-mode knowledge from manuals / FMEA documents."""
from core.declare import agent


@agent(
    name="manuals_expert",
    description="Finds known failure modes and guidance in uploaded manuals / FMEA "
                "documents (RAG).",
    tools=["search_fmea", "search_docs"],
    when_to_use="you have a symptom, parameter, or defect type and want the known failure "
                "mechanism or recommended check from uploaded manuals/FMEA",
    how_to_use="query with the symptom/parameter/defect; it quotes passages and cites the "
               "source document, or says plainly that nothing relevant was found",
    what_to_use_for="retrieving and citing failure-mode knowledge from uploaded text documents",
    what_not_to_use_for="text/document retrieval only — NOT for numeric/tabular analysis, "
                        "association testing, wafer maps, or FDC traces; cannot compute statistics",
)
def manuals_expert(ctx):
    return (
        "You are a process-knowledge expert. Given a symptom, parameter, or defect, "
        "search the uploaded manuals and FMEA documents for known failure modes and "
        "recommended checks. Quote the relevant passages and cite the document. "
        "If nothing relevant is found, say so plainly."
    )
