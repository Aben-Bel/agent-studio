"""Persistent audit trail for investigations.

Every orchestrator event (each reasoning step, tool call, tool result, data
touched, human checkpoint) is written to app.db. This is what makes the platform
"100% visible": any investigation can be replayed and inspected after the fact,
and it doubles as a compliance log. Read it via /runs and /runs/{chat_id}."""
import json
from datetime import datetime, timezone
from sqlalchemy import text as sql
from connectors.datastore import _engine


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _init():
    with _engine("local").begin() as cx:
        cx.execute(sql("create table if not exists runs "
                       "(chat_id text primary key, agent text, started text, "
                       "updated text, status text, steps int)"))
        cx.execute(sql("create table if not exists run_steps "
                       "(chat_id text, seq int, ts text, type text, data text)"))


def start_run(chat_id, agent):
    if not chat_id:
        return
    _init()
    with _engine("local").begin() as cx:
        cx.execute(sql("insert into runs(chat_id,agent,started,updated,status,steps) "
                       "values (:c,:a,:t,:t,'running',0) "
                       "on conflict(chat_id) do update set status='running', updated=:t"),
                   {"c": chat_id, "a": agent, "t": _now()})


def record(chat_id, event):
    """Append one streamed event to the audit trail."""
    if not chat_id:
        return
    _init()
    with _engine("local").begin() as cx:
        seq = cx.execute(sql("select coalesce(max(seq),0)+1 from run_steps where chat_id=:c"),
                         {"c": chat_id}).scalar()
        cx.execute(sql("insert into run_steps(chat_id,seq,ts,type,data) "
                       "values (:c,:s,:t,:ty,:d)"),
                   {"c": chat_id, "s": seq, "t": _now(),
                    "ty": event.get("type"), "d": json.dumps(event.get("data", {}))})
        cx.execute(sql("update runs set updated=:t, steps=:s where chat_id=:c"),
                   {"t": _now(), "s": seq, "c": chat_id})


def finish_run(chat_id, status):
    if not chat_id:
        return
    _init()
    with _engine("local").begin() as cx:
        cx.execute(sql("update runs set status=:st, updated=:t where chat_id=:c"),
                   {"st": status, "t": _now(), "c": chat_id})


def list_runs(limit=50):
    _init()
    with _engine("local").connect() as cx:
        rows = cx.execute(sql("select chat_id,agent,started,updated,status,steps "
                              "from runs order by updated desc limit :n"), {"n": limit}).fetchall()
    return [{"chat_id": r[0], "agent": r[1], "started": r[2], "updated": r[3],
             "status": r[4], "steps": r[5]} for r in rows]


def get_run(chat_id):
    _init()
    with _engine("local").connect() as cx:
        steps = cx.execute(sql("select seq,ts,type,data from run_steps "
                               "where chat_id=:c order by seq"), {"c": chat_id}).fetchall()
    return {"chat_id": chat_id,
            "steps": [{"seq": s[0], "ts": s[1], "type": s[2], "data": json.loads(s[3])}
                      for s in steps]}
