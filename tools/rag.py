from pydantic import BaseModel
from core.declare import tool
from connectors import memory


class Query(BaseModel):
    query: str


@tool("search_docs",
      "Search the uploaded documents (RAG) for passages relevant to a query.",
      Query,
      limits="Searches indexed uploaded documents only; cannot query SQL tables or read un-indexed files.")
def search_docs(query):
    hits = memory.search(query, k=4)
    return "\n\n".join(hits) if hits else "No relevant documents found."
