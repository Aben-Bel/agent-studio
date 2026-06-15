import inspect
import threading
from queue import Queue
from .registry import AGENTS, TOOLS, SKILLS, MCP, STAGES
from . import model, pipeline, runs
from .config import cfg


def _params_schema(fn):
    """Build a JSON schema from a function's signature so the model knows what
    arguments to pass. Skills declare no pydantic model, so we infer one here -
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
# (In-memory for the demo - swap this dict for Redis/SQL to survive restarts.)
# ----------------------------------------------------------------------------
SESSIONS: dict = {}

HUMAN_TOOL = "ask_human"        # calling this pauses the run for human input
CONSULT_TOOL = "consult_agent"  # calling this recruits another agent (multi-agent)

# House style enforced on EVERY agent + synthesis, centrally. Engineering output:
# no decoration, every claim referenced, every finding reproducible.
STYLE = (
    "OUTPUT RULES (strict, override any other style):\n"
    "- No emojis. No filler, hype, or flattery. State findings directly.\n"
    "- Be concise: short sentences, tables/lists over prose.\n"
    "- Reference every claim: cite the table.column, document name + section, or the "
    "exact value you used. No unreferenced assertions.\n"
    "- Be replicable: include the exact SQL, tool name + arguments, or steps so another "
    "engineer can reproduce the result.\n"
    "- If something is unknown or a tool is not implemented, say so plainly."
)


def _style(base):
    return (STYLE + "\n\n" + base) if base else STYLE


def capabilities():
    return {
        "agents": [{"name": a.name, "description": a.description, "tools": a.tools}
                   for a in AGENTS.all().values()],
        "tools": [{"name": t.name, "description": t.description,
                   "version": t.version, "owner": t.owner, "tags": t.tags}
                  for t in TOOLS.all().values()],
        "skills": [{"name": s.name, "description": s.description}
                   for s in SKILLS.all().values()],
        "mcp": [{"name": m.name, "description": m.description, "config": m.config}
                for m in MCP.all().values()],
        "stages": [{"name": s.name, "order": s.order, "description": s.description}
                   for s in sorted(STAGES.all().values(), key=lambda x: x.order)],
    }


def _specs(names):
    out = []
    for n in names:
        if n in TOOLS.all():
            t = TOOLS.get(n)
            spec = {"name": t.name, "description": t.description,
                    "schema": t.args.model_json_schema()}
            if t.returns is not None:
                spec["returns"] = t.returns.model_json_schema()
            out.append(spec)
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


def _run_subagent(parent_sess, sub_name, task):
    """Recruit and run a specialist agent on a sub-task. Streams the sub-agent's
    every step (tagged depth=1 so the UI can nest it) and returns its conclusion.
    Generator: `result = yield from _run_subagent(...)`."""
    if sub_name not in AGENTS.all() or sub_name == parent_sess["agent"]:
        return f"Cannot recruit agent '{sub_name}'. Available: " \
               f"{[n for n in AGENTS.all() if n != parent_sess['agent']]}"
    agent = AGENTS.get(sub_name)
    system = _style(agent.fn({}) if callable(agent.fn) else "")
    sub = {"chat_id": parent_sess.get("chat_id"), "agent": sub_name, "system": system,
           "msgs": [{"role": "user", "content": task}], "status": "running",
           "pending": None, "step": 0, "inbox": []}
    yield {"type": "agent_switch",
           "data": {"agent": sub_name, "description": agent.description, "role": "recruited",
                    "by": parent_sess["agent"], "task": task, "depth": 1,
                    "chat_id": parent_sess.get("chat_id")}}
    final = ""
    for ev in _drive(sub):
        d = dict(ev["data"]); d["depth"] = 1; d["agent_scope"] = sub_name
        yield {"type": ev["type"], "data": d}
        if ev["type"] == "final":
            final = ev["data"].get("message", "")
    yield {"type": "agent_switch",
           "data": {"agent": parent_sess["agent"], "role": "resumed",
                    "description": AGENTS.get(parent_sess["agent"]).description,
                    "chat_id": parent_sess.get("chat_id")}}
    return f"[{sub_name}] {final}" if final.strip() else f"[{sub_name}] (no findings)"


def _new_session(chat_id, agent_name):
    agent = AGENTS.get(agent_name)
    system = _style(agent.fn({}) if callable(agent.fn) else "")
    sess = {"chat_id": chat_id, "agent": agent_name, "system": system,
            "msgs": [], "status": "idle", "pending": None, "step": 0, "inbox": []}
    SESSIONS[chat_id] = sess
    return sess


def _drive(sess):
    """Advance one session until it finishes (final) or pauses for a human
    (needs_human). Mutates the session as it goes and yields UI events. Re-enter
    it after a human reply to continue from exactly where it stopped."""
    agent = AGENTS.get(sess["agent"])
    allow = sess.get("allow_tools")
    funcs = _specs([t for t in agent.tools if not allow or t in allow])
    sess["status"] = "running"

    while sess["step"] < cfg.max_steps:
        # Catch up on any context the user added since the last step. The inbox is
        # drained at a clean point (between tool rounds), so a running agent picks
        # up new uploads/notes on its next step without breaking the conversation.
        if sess.get("inbox"):
            new, sess["inbox"] = sess["inbox"], []
            for c in new:
                sess["msgs"].append({"role": "user",
                                     "content": f"[Additional context the user just added]\n{c}"})
                yield {"type": "context_added",
                       "data": {"text": c[:200], "chat_id": sess.get("chat_id")}}

        sess["step"] += 1
        yield {"type": "progress", "data": {"message": f"reasoning (step {sess['step']})"}}
        try:
            r = model.complete(sess["msgs"], funcs, sess["system"])
        except Exception as e:
            sess["status"] = "error"
            yield {"type": "error", "data": {"message": str(e)}}
            return

        if r.tool_calls:
            if (r.content or "").strip():     # surface the model's reasoning before it acts
                yield {"type": "thinking", "data": {"text": r.content}}
            sess["msgs"].append({"role": "assistant", "tool_calls": r.tool_calls})
            for tc in r.tool_calls:
                name = tc["name"]
                kind = ("agent" if name == CONSULT_TOOL
                        else "skill" if name in SKILLS.all() else "tool")
                yield {"type": "tool_call",
                       "data": {"kind": kind, "name": name, "args": tc["arguments"]}}

                if name == HUMAN_TOOL:                       # ---- human-in-the-loop ----
                    q = (tc["arguments"] or {}).get("question") or "The agent needs your input."
                    if sess.get("no_pause"):
                        # Parallel team mode cannot pause one of N concurrent agents.
                        # Don't fake a pause; tell the agent to proceed and note the gap.
                        result = ("No human prompt is available in parallel mode. Proceed "
                                  "with the data you have and clearly note this missing "
                                  "input in your findings: " + q)
                        yield {"type": "tool_result",
                               "data": {"kind": "tool", "name": name, "result": result}}
                        sess["msgs"].append({"role": "tool", "name": name,
                                             "tool_call_id": tc["id"], "content": result})
                        continue
                    sess["pending"] = {"tool_call_id": tc["id"], "name": name}
                    sess["status"] = "awaiting_human"
                    yield {"type": "needs_human",
                           "data": {"question": q, "chat_id": sess["chat_id"]}}
                    return                                   # suspend; resume on next reply (single-agent)

                if name == CONSULT_TOOL:                     # ---- recruit another agent ----
                    args = tc["arguments"] or {}
                    sub = args.get("agent", "")
                    task = args.get("task") or args.get("question") or ""
                    result = yield from _run_subagent(sess, sub, task)
                else:
                    result = _dispatch(name, tc["arguments"])

                # Full result flows to the UI + audit trail (the trace truncates for
                # display but lets you expand to see exactly what happened).
                yield {"type": "tool_result",
                       "data": {"kind": kind, "name": name, "result": result}}
                sess["msgs"].append({"role": "tool", "name": name,
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


def start_or_resume(chat_id, agent_name, message, allow_tools=None, sources=None):
    """Stateful entry point used by the API. Starts a new chat or continues an
    existing one by chat_id. The human's `message` either opens a new turn or
    answers a pending `ask_human` pause. Optional tool/source restrictions scope
    the run, matching the team mode."""
    sess = SESSIONS.get(chat_id)
    if sess is None:
        sess = _new_session(chat_id, agent_name)
        sess["allow_tools"] = set(allow_tools) if allow_tools else None
        runs.start_run(chat_id, agent_name)
        agent = AGENTS.get(agent_name)
        ev = {"type": "agent_switch",
              "data": {"agent": agent.name, "description": agent.description,
                       "chat_id": chat_id}}
        runs.record(chat_id, ev)
        yield ev

    if sess.get("pending"):
        # Resuming a human-in-the-loop pause: the reply is the tool's result.
        p = sess.pop("pending")
        sess["msgs"].append({"role": "tool", "name": p["name"],
                             "tool_call_id": p["tool_call_id"], "content": message})
    else:
        scoped = (f"Use ONLY these data sources / tables: {', '.join(sources)}.\n\n{message}"
                  if sources else message)
        sess["msgs"].append({"role": "user", "content": scoped})
        runs.record(chat_id, {"type": "user_message", "data": {"text": message}})

    # Every streamed event is persisted to the audit trail (full visibility).
    for ev in _drive(sess):
        runs.record(chat_id, ev)
        yield ev
    runs.finish_run(chat_id, sess["status"])


def specialist_agents():
    """Agents meant to be run as a team (everyone except supervisors that recruit)."""
    return [n for n, a in AGENTS.all().items() if CONSULT_TOOL not in (a.tools or [])]


TEAM_SESSIONS: dict = {}   # chat_id -> [{"task", "synthesis"}] for follow-up continuity


def run_team(chat_id, task, agent_names=None, allow_tools=None, sources=None):
    """Run multiple agents IN PARALLEL on the same task, stream their interleaved
    steps (each tagged with its agent), then synthesize one conclusion. This is the
    default investigation mode: list the agents, fire them at once, combine.
    Optionally restrict the tools agents may use and the data sources in scope."""
    names = [n for n in (agent_names or specialist_agents()) if n in AGENTS.all()]
    if not names:
        names = specialist_agents()
    allow = set(allow_tools) if allow_tools else None

    history = TEAM_SESSIONS.setdefault(chat_id, [])
    context = ""
    if history:
        context = ("Earlier in this investigation:\n" +
                   "\n".join(f"- Q: {h['task']}\n  Conclusion: {h['synthesis'][:300]}"
                             for h in history) + "\n\n")
    scope = ""
    if sources:
        scope = f"Use ONLY these data sources / tables: {', '.join(sources)}.\n\n"
    prompt = context + scope + task

    runs.start_run(chat_id, "team")
    def emit(ev):
        runs.record(chat_id, ev)
        return ev

    yield emit({"type": "user_message", "data": {"text": task}})
    yield emit({"type": "agent_switch",
                "data": {"agent": "team", "role": "dispatch", "agents": names, "chat_id": chat_id}})

    q = Queue()
    results = {}

    def work(name):
        try:
            agent = AGENTS.get(name)
            system = _style(agent.fn({}) if callable(agent.fn) else "")
            sub = {"chat_id": chat_id, "agent": name, "system": system,
                   "msgs": [{"role": "user", "content": prompt}], "status": "running",
                   "pending": None, "step": 0, "inbox": [], "allow_tools": allow,
                   "no_pause": True}
            q.put({"type": "agent_switch",
                   "data": {"agent": name, "role": "working", "depth": 1, "agent_scope": name}})
            final = ""
            for ev in _drive(sub):
                d = dict(ev["data"]); d["agent_scope"] = name; d["depth"] = 1
                q.put({"type": ev["type"], "data": d})
                if ev["type"] == "final":
                    final = ev["data"].get("message", "")
            results[name] = final
        except Exception as e:
            results[name] = f"(error: {e})"
            q.put({"type": "error", "data": {"agent_scope": name, "depth": 1, "message": str(e)}})
        finally:
            q.put({"__done__": name})

    threads = [threading.Thread(target=work, args=(n,), daemon=True) for n in names]
    for t in threads:
        t.start()
    done = 0
    while done < len(names):
        item = q.get()
        if "__done__" in item:
            done += 1
            continue
        yield emit(item)
    for t in threads:
        t.join(timeout=1)

    # One agent selected -> return its findings directly; 2+ -> synthesize across them.
    if len(names) == 1:
        synthesis = list(results.values())[0] or "(no findings)"
    else:
        synthesis = _synthesize(task, results)
    history.append({"task": task, "synthesis": synthesis})
    runs.finish_run(chat_id, "done")
    yield emit({"type": "final", "data": {"message": synthesis, "chat_id": chat_id, "synthesis": True}})


def _synthesize(task, results):
    """Combine the parallel specialists' findings into one conclusion."""
    findings = "\n\n".join(f"### {n}\n{r}" for n, r in results.items())
    if cfg.mock_llm:
        return "# Combined specialist findings\n\n" + findings
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"Investigation question: {task}\n\nSpecialist findings:\n{findings}\n\n"
              "Synthesize a concise root-cause conclusion with a recommended countermeasure. "
              "Cite which specialist found what and the data/document behind each point. "
              "Use plain markdown."}],
            [], _style("You are the lead RCA investigator synthesizing your team's parallel findings."))
        concl = (r.content or "").strip()
    except Exception as e:
        concl = ""
        findings = f"(synthesis model error: {e})\n\n" + findings
    return ((concl + "\n\n---\n\n## Specialist findings\n\n" + findings)
            if concl else ("# Specialist findings\n\n" + findings))


def add_context(chat_id, text):
    """Add context to a session WHILE it may be running. It lands in the session
    inbox and is drained on the orchestrator's next step (or next turn), so the
    agent smoothly catches up. Also sweeps any pending uploads so freshly added
    documents are indexed and immediately searchable."""
    try:
        pipeline.run_pending()
    except Exception:
        pass
    sess = SESSIONS.get(chat_id)
    if sess is None:
        return {"ok": False, "error": f"no session '{chat_id}'"}
    if (text or "").strip():
        sess.setdefault("inbox", []).append(text.strip())
    return {"ok": True, "queued": len(sess.get("inbox", [])), "status": sess["status"]}


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
    system = _style(agent.fn({}) if callable(agent.fn) else "")
    sess = {"chat_id": None, "agent": agent_name, "system": system,
            "msgs": list(history or []) + [{"role": "user", "content": message}],
            "status": "running", "pending": None, "step": 0, "inbox": []}
    yield {"type": "agent_switch",
           "data": {"agent": agent.name, "description": agent.description}}
    yield from _drive(sess)
