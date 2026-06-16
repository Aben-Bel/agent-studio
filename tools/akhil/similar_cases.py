"""Tool: find similar historical RCA cases using RAG search.

Replaces the stub in tools/rca/stubs.py with a real implementation.
Searches the vector store (uploaded FMEA docs, manuals, past RCA reports)
for chunks that match the defect signature, and returns the closest
historical cases with their confirmed root cause."""
from pydantic import BaseModel
from core.declare import tool
from connectors import memory


class SimilarCasesArgs(BaseModel):
    signature: str          # defect symptom or pattern to search for
    top_k: int = 3          # number of similar cases to return


@tool(
    "search_similar_cases",
    "Search uploaded FMEA documents, manuals, and historical RCA reports for past "
    "cases that match the given defect signature or symptom. Returns the closest "
    "matching passages with confirmed root causes. Use when you have a defect pattern "
    "and want to know if it has occurred before and what fixed it.",
    SimilarCasesArgs,
    owner="akhil",
    tags=["cases", "rag", "fmea", "history", "rca"],
)
def find_similar_cases(signature, top_k=3):
    if not signature or not signature.strip():
        return "Please provide a defect signature or symptom to search for."

    results = memory.search(signature, k=top_k)

    if not results:
        return (f"No similar cases found for: '{signature}'. "
                f"Upload FMEA documents or historical RCA reports to enable case matching.")

    lines = [
        f"Similar historical cases for: '{signature}'",
        f"({len(results)} result(s) from uploaded knowledge base)",
        "",
    ]
    for i, chunk in enumerate(results, 1):
        lines.append(f"Case {i}:")
        lines.append(chunk.strip())
        lines.append("")

    return "\n".join(lines)
