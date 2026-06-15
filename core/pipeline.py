"""Document-processing pipeline.

Uploads RECORD a document (status=pending); the pipeline PROCESSES it by running
every discovered @stage in order. A sweep (run_pending) picks up anything still
pending — so nothing is silently "left behind", and you can replay by resetting
status. Stages are drop-in files in pipeline/ (see core.declare.stage)."""
from sqlalchemy import text as sql
from connectors.datastore import _engine
from .registry import STAGES


def _init():
    with _engine("local").begin() as cx:
        cx.execute(sql("create table if not exists documents "
                       "(source text primary key, status text, text text, error text)"))


def add_upload(source, text):
    """Record a raw document to be processed. Idempotent per source."""
    _init()
    with _engine("local").begin() as cx:
        cx.execute(sql("insert into documents(source,status,text,error) "
                       "values (:s,'pending',:t,null) "
                       "on conflict(source) do update set status='pending', text=:t, error=null"),
                   {"s": source, "t": text})


def _stages():
    return sorted(STAGES.all().values(), key=lambda s: s.order)


def run_pending():
    """The sweep: process every pending document through all stages, in order.
    Returns a summary of what was processed. Safe to call anytime."""
    _init()
    with _engine("local").connect() as cx:
        pending = cx.execute(sql("select source, text from documents where status='pending'")).fetchall()

    done = []
    for source, text in pending:
        doc = {"source": source, "text": text}
        try:
            for st in _stages():
                doc = st.fn(doc) or doc
            _set(source, "done", None)
            done.append({"source": source, "stages": [s.name for s in _stages()]})
        except Exception as e:
            _set(source, "error", str(e))
            done.append({"source": source, "error": str(e)})
    return done


def reset(source=None):
    """Mark a document (or all) pending again so the next sweep re-processes it."""
    _init()
    with _engine("local").begin() as cx:
        if source:
            cx.execute(sql("update documents set status='pending' where source=:s"), {"s": source})
        else:
            cx.execute(sql("update documents set status='pending'"))


def _set(source, status, error):
    with _engine("local").begin() as cx:
        cx.execute(sql("update documents set status=:st, error=:e where source=:s"),
                   {"st": status, "e": error, "s": source})


def status():
    """Counts by status + the list of pipeline stages (for the orchestrator/UI)."""
    _init()
    with _engine("local").connect() as cx:
        rows = cx.execute(sql("select status, count(*) from documents group by status")).fetchall()
    return {"counts": {s: n for s, n in rows},
            "pending": dict(rows).get("pending", 0),
            "stages": [{"name": s.name, "order": s.order, "description": s.description}
                       for s in _stages()]}
