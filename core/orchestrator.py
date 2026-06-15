import inspect
from .registry import AGENTS, TOOLS, SKILLS, MCP
from . import model
from .config import cfg


def _params_schema(fn):
    """Build a JSON schema from a function's signature so the model knows what
    arguments to pass. Skills declare no pydantic model, so we infer one here —
    contributors still just write a plain function."""
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        props[name] = {"type": "string"}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


# ----------------------------------------------------------------------------
# Sessions: the orchestrator is a human-in-the-loop, resumable conversation, not
# a one-shot call. A human starts a chat; the orchestrator streams every step;
# it can PAUSE to ask the human something (ask_human) and remembers exactly where
# it stopped; when the human replies it CONTINUES the same session. State lives
# here, keyed by chat_id, so the client never has to resend the whole history.
# (In-memory for the demo — swap this dict for Redis/SQL to survive restarts.)
# ----------------------------------------------------------------------------
SESSIONS: dict = {}

HUMAN_TOOL = "ask_human"   # calling this pauses the run for human input


def capabilities():
    return {
        "agents": [{"name": a.name, "description": a.description, "tools": a.tools}
                   for a in AGENTS.all().values()],
        "tools": [{"name": t.name, "description": t.description}
                  for t in TOOLS.all().values()],
        "skills": [{"name": s.name, "description": s.description}
                   for s in SKILLS.all().values()],
        "mcp": [{"name": m.name, "description": m.description, "config": m.config}
                for m in MCP.all().values()],
    }


def _specs(names):
    out = []
    for n in names:
        if n in TOOLS.all():
            t = TOOLS.get(n)
            out.append({"name": t.name, "description": t.description,
                        "schema": t.args.model_json_schema()})
        elif n in SKILLS.all():
            s = SKILLS.get(n)
            out.append({"name": s.name, "description": s.description,
                        "schema": _params_schema(s.fn)})
    return out


def _dispatch(name, args):
    """A failing tool/skill returns an error string; the agent continues."""
    try:
        if name in TOOLS.all():
            t = TOOLS.get(name)
            return str(t.fn(**t.args(**args).model_dump()))
        if name in SKILLS.all():
            fn = SKILLS.get(name).fn
            params = inspect.signature(fn).parameters
            safe = {k: v for k, v in (args or {}).items() if k in params}
            return str(fn(**safe))
        return f"unknown function '{name}'"
    except Exception as e:
        return f"ERROR in '{name}': {e}"


def _new_session(chat_id, agent_name):
    agent = AGENTS.get(agent_name)
    system = agent.fn({}) if callable(agent.fn) else ""
    sess = {"chat_id": chat_id, "agent": agent_name, "system": system,
            "msgs": [], "status": "idle", "pending": None, "step": 0}
    SESSIONS[chat_id] = sess
    return sess


def _drive(sess):
    """Advance one session until it finishes (final) or pauses for a human
    (needs_human). Mutates the session as it goes and yields UI events. Re-enter
    it after a human reply to continue from exactly where it stopped."""
    agent = AGENTS.get(sess["agent"])
    funcs = _specs(agent.tools)
    sess["status"] = "running"

    while sess["step"] < cfg.max_steps:
        sess["step"] += 1
        yield {"type": "progress", "data": {"message": f"reasoning (step {sess['step']})"}}
        try:
            r = model.complete(sess["msgs"], funcs, sess["system"])
        except Exception as e:
            sess["status"] = "error"
            yield {"type": "error", "data": {"message": str(e)}}
            return

        if r.tool_calls:
            sess["msgs"].append({"role": "assistant", "tool_calls": r.tool_calls})
            for tc in r.tool_calls:
                kind = "skill" if tc["name"] in SKILLS.all() else "tool"
                yield {"type": "tool_call",
                       "data": {"kind": kind, "name": tc["name"], "args": tc["arguments"]}}

                if tc["name"] == HUMAN_TOOL:                 # ---- pause for the human ----
                    q = (tc["arguments"] or {}).get("question") or "The agent needs your input."
                    sess["pending"] = {"tool_call_id": tc["id"], "name": tc["name"]}
                    sess["status"] = "awaiting_human"
                    yield {"type": "needs_human",
                           "data": {"question": q, "chat_id": sess["chat_id"]}}
                    return                                   # suspend; resume on next reply

                result = _dispatch(tc["name"], tc["arguments"])
                yield {"type": "tool_result",
                       "data": {"kind": kind, "name": tc["name"], "result": result[:400]}}
                sess["msgs"].append({"role": "tool", "name": tc["name"],
                                     "tool_call_id": tc["id"], "content": result})
            continue

        sess["msgs"].append({"role": "assistant", "content": r.content or ""})
        sess["status"] = "done"
        sess["step"] = 0                                     # fresh budget for the next turn
        yield {"type": "final", "data": {"message": r.content or "", "chat_id": sess["chat_id"]}}
        return

    sess["status"] = "done"
    sess["step"] = 0
    yield {"type": "final",
           "data": {"message": "(stopped after max steps)", "chat_id": sess["chat_id"]}}


def start_or_resume(chat_id, agent_name, message):
    """Stateful entry point used by the API. Starts a new chat or continues an
    existing one by chat_id. The human's `message` either opens a new turn or
    answers a pending `ask_human` pause."""
    sess = SESSIONS.get(chat_id)
    if sess is None:
        sess = _new_session(chat_id, agent_name)
        agent = AGENTS.get(agent_name)
        yield {"type": "agent_switch",
               "data": {"agent": agent.name, "description": agent.description,
                        "chat_id": chat_id}}

    if sess.get("pending"):
        # Resuming a human-in-the-loop pause: the reply is the tool's result.
        p = sess.pop("pending")
        sess["msgs"].append({"role": "tool", "name": p["name"],
                             "tool_call_id": p["tool_call_id"], "content": message})
    else:
        sess["msgs"].append({"role": "user", "content": message})

    yield from _drive(sess)


def session_state(chat_id):
    """UI-friendly snapshot so the frontend can restore a chat (what it said,
    its status, and any pending question it stopped on)."""
    sess = SESSIONS.get(chat_id)
    if sess is None:
        return {"chat_id": chat_id, "exists": False}
    transcript = []
    for m in sess["msgs"]:
        role = m.get("role")
        if role == "user":
            transcript.append({"role": "user", "text": m.get("content", "")})
        elif role == "assistant" and m.get("content"):
            transcript.append({"role": "assistant", "text": m["content"]})
    pending = None
    if sess.get("pending"):
        # surface the last question asked
        for m in reversed(sess["msgs"]):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc["name"] == HUMAN_TOOL:
                        pending = (tc["arguments"] or {}).get("question")
                        break
            if pending:
                break
    return {"chat_id": chat_id, "exists": True, "agent": sess["agent"],
            "status": sess["status"], "pending_question": pending,
            "transcript": transcript}


def list_sessions():
    return [{"chat_id": s["chat_id"], "agent": s["agent"], "status": s["status"],
             "turns": sum(1 for m in s["msgs"] if m.get("role") == "user")}
            for s in SESSIONS.values()]


# ----------------------------------------------------------------------------
# Legacy stateless entry point (kept for existing tests and the old contract):
# runs to completion with no persisted session.
# ----------------------------------------------------------------------------
def run(agent_name, message, history=None):
    agent = AGENTS.get(agent_name)
    system = agent.fn({}) if callable(agent.fn) else ""
    sess = {"chat_id": None, "agent": agent_name, "system": system,
            "msgs": list(history or []) + [{"role": "user", "content": message}],
            "status": "running", "pending": None, "step": 0}
    yield {"type": "agent_switch",
           "data": {"agent": agent.name, "description": agent.description}}
    yield from _drive(sess)
