from pydantic import BaseModel
from core.declare import tool
from connectors import datastore, memory


class Empty(BaseModel):
    pass


@tool("list_data_sources",
      "List ALL data the user has: connected SQL sources/tables AND uploaded "
      "documents (PDFs/manuals indexed for search). Use this to answer 'what data "
      "do I have'.", Empty)
def list_data_sources():
    parts = []
    for s in datastore.list_sources():
        tables = ", ".join(s["tables"]) or "(no tables)"
        parts.append(f'SQL source "{s["name"]}" [{s["dialect"]}]: {tables}')
    docs = memory.list_documents()
    if docs:
        parts.append("Uploaded documents (searchable via search_docs / search_fmea): "
                     + ", ".join(f'{d["source"]} ({d["chars"]} chars)' for d in docs))
    return "\n".join(parts) or "No data sources connected yet."


class QueryArgs(BaseModel):
    sql: str                     # a read-only SELECT
    source: str = "local"        # which connected source to query


@tool("query_data",
      "Run a read-only SQL SELECT against a connected data source and return the "
      "rows. Use list_data_sources first to see source names and tables.",
      QueryArgs)
def query_data(sql, source="local"):
    # Reads are tolerant; mutations are refused - the data sources are not a
    # write path for the agent.
    head = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
    if head not in ("select", "with"):
        return "Only read-only SELECT/WITH queries are allowed."
    try:
        cols, rows = datastore.run_sql(sql, source=source)
    except Exception as e:
        return f"query failed: {e}"
    if not rows:
        return "(no rows)"
    out = [" | ".join(cols)] if cols else []
    for r in rows[:50]:
        out.append(" | ".join("" if v is None else str(v) for v in r))
    if len(rows) > 50:
        out.append(f"... ({len(rows)} rows total, showing 50)")
    return "\n".join(out)
