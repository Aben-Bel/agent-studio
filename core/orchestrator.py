import inspect
import threading
from queue import Queue
from .registry import AGENTS, TOOLS, SKILLS, MCP, STAGES, EXPORTERS
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
EXPORT_TOOL = "prepare_download"  # calling this generates a downloadable artifact

# Platform primitives every agent always gets (on top of its own specialist tools),
# so no agent is ever "data-blind" or unable to produce an output regardless of how
# the question was routed or which tools the user toggled: see + load the data, and
# generate a download. Only the ones actually registered are injected.
BUILTIN_TOOLS = ["list_data_sources", "load_uploaded_csv", EXPORT_TOOL]

# Friendly aliases -> exporter name, so the agent can say pdf/slides/report/latex.
_FORMAT_ALIASES = {
    "pdf": "presentation_pdf", "slides": "presentation_pdf", "slide": "presentation_pdf",
    "deck": "presentation_pdf", "slide deck": "presentation_pdf", "presentation": "presentation_pdf",
    "ppt": "presentation_pdf", "powerpoint": "presentation_pdf",
    "report": "report_md", "md": "report_md", "markdown": "report_md",
    "document": "report_md", "doc": "report_md", "report_md": "report_md",
    "tex": "presentation_tex", "latex": "presentation_tex", "source": "presentation_tex",
    "presentation_pdf": "presentation_pdf", "presentation_tex": "presentation_tex",
}

# House style enforced on EVERY agent + synthesis, centrally. Engineering output:
# no decoration, every claim referenced, every finding reproducible.
STYLE = (
    "OUTPUT RULES (strict, override any other style):\n"
    "- BE BRIEF. Answer only what was asked, in the fewest words. Aim for a few "
    "sentences or one small table. Do NOT add extra sections (no 'Recommended Next "
    "Steps', 'Confidence Limitations', 'Summary', etc.) unless explicitly asked.\n"
    "- No emojis. No filler, hype, flattery, or restating the question.\n"
    "- Reference each claim with the table.column, document, or exact value used.\n"
    "- If something is unknown, missing, or a tool is not implemented, say so in one line.\n"
    "- If the user asks to download, export, save, or get a PDF / slide deck / "
    "presentation / report / document of the findings, CALL the prepare_download tool "
    "(format 'presentation_pdf' for slides/PDF, 'report_md' for a report). You CAN "
    "produce downloadable files - never say you cannot."
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


def _prepare_download(chat_id, fmt_arg, title=None):
    """Resolve a download request from an agent into a UI artifact event + a tool
    result that tells the agent the file is ready. Generation itself happens lazily
    when the user clicks (so the just-finished findings are always included)."""
    from . import export as export_svc
    if not chat_id:
        return None, "Cannot prepare a download outside a saved investigation."
    fmt = _FORMAT_ALIASES.get((fmt_arg or "").strip().lower(), "")
    if fmt not in EXPORTERS.all():
        fmt = "presentation_pdf" if "presentation_pdf" in EXPORTERS.all() else "report_md"
    decl = EXPORTERS.get(fmt)
    available = export_svc._available(decl)
    if not available and fmt == "presentation_pdf" and "presentation_tex" in EXPORTERS.all():
        fmt, decl, available = "presentation_tex", EXPORTERS.get("presentation_tex"), True
    ev = {"type": "artifact",
          "data": {"format": fmt, "label": decl.label, "extension": decl.extension,
                   "available": available, "title": title, "chat_id": chat_id}}
    result = (f"Download prepared: {decl.label}. A download button is now shown to the "
              "user in the chat. Tell them it is ready; do not paste the file contents.")
    return ev, result


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
    # Platform primitives (data discovery + download) are ALWAYS available to every
    # agent, regardless of tool restrictions, so no agent ever falsely claims it has
    # no data or cannot produce a file. prepare_download is intercepted below; the
    # data tools dispatch normally.
    have = {f["name"] for f in funcs}
    extra = [b for b in BUILTIN_TOOLS if b in TOOLS.all() and b not in have]
    if extra:
        funcs = funcs + _specs(extra)
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

                if name == EXPORT_TOOL:                       # ---- generate a download ----
                    args = tc["arguments"] or {}
                    art, result = _prepare_download(sess.get("chat_id"),
                                                    args.get("format"), args.get("title"))
                    if art:
                        yield art
                    yield {"type": "tool_result",
                           "data": {"kind": "tool", "name": name, "result": result}}
                    sess["msgs"].append({"role": "tool", "name": name,
                                         "tool_call_id": tc["id"], "content": result})
                    continue

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
        scoped = ("Use ONLY these data sources, tables, and documents: "
                  f"{', '.join(sources)}. Ignore any not listed.\n\n{message}"
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


TEAM_SESSIONS: dict = {}    # chat_id -> [{"task", "synthesis"}] for follow-up continuity
CLARIFY_PENDING: dict = {}  # chat_id -> {"task"} when the team asked the user to clarify


def suggest_questions(context=""):
    """A few short questions to help the user (initial starters, or follow-ups).
    Data-aware: knows what tables/documents are loaded. Returns <= 4 questions."""
    from connectors import datastore, memory
    tables = [t for s in datastore.list_sources() for t in s["tables"]]
    docs = [d["source"] for d in memory.list_documents()]
    fallback = ["What can you do?",
                "Which process step has the most defects?",
                "What is the top defect driver?"]
    if cfg.mock_llm:
        return fallback
    info = f"Loaded tables: {', '.join(tables) or 'none'}. Documents: {', '.join(docs) or 'none'}."
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"{info}\n{context}\n\nSuggest 3 short, specific questions a yield-analysis "
              "engineer might ask next given this data. Each under 9 words, concrete. "
              "One per line, no numbering, no quotes."}],
            [], "You suggest concise, useful next questions. Output only the questions.")
        qs = [ln.strip("-*0123456789. \"'") for ln in (r.content or "").splitlines() if ln.strip()]
        qs = [q for q in qs if 3 < len(q) < 90][:4]
        return qs or fallback
    except Exception:
        return fallback


def _route_agents(task, names):
    """LLM picks the minimal set of relevant specialists for THIS question, from
    the ones the user selected. Routing, not always fan-out. Falls back to all."""
    if len(names) <= 1 or cfg.mock_llm:
        return names
    catalog = "\n".join(f"- {n}: {AGENTS.get(n).description}" for n in names)
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"Question: {task}\n\nAvailable specialists:\n{catalog}\n\n"
              "List ONLY the specialist names actually needed to answer THIS question, "
              "comma-separated. Omit irrelevant ones. If genuinely unsure, include it."}],
            [], _style("You route a question to the minimal set of relevant specialists."))
        picked = (r.content or "").replace("\n", ",").lower()
        sel = [n for n in names if n.lower() in picked]
        return sel or names
    except Exception:
        return names


def _needs_clarification(task, results):
    """LLM decides (not hardcoded) whether the specialists flagged the input as
    ambiguous such that ONE question to the user would materially change the answer.
    Returns the question, or None."""
    findings = "\n\n".join(f"{n}: {(r or '')[:500]}" for n, r in results.items())
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"User question: {task}\n\nSpecialist findings:\n{findings}\n\n"
              "Decide whether to ask the user ONE clarifying question before answering. "
              "Ask if the question hinges on an ambiguous reference the specialists had to "
              "GUESS the meaning of - e.g. a bare value/identifier like '844' that could be "
              "a wafer id, lot id, or something else - or if specialists interpreted it "
              "differently. Do NOT ask merely because data is missing or a tool is a stub. "
              "If you should ask, reply with exactly one line: CLARIFY: <one short question>. "
              "Otherwise reply exactly: OK"}],
            [], _style("You decide whether to ask the user one clarifying question."))
        out = (r.content or "").strip()
    except Exception:
        return None
    return out.split(":", 1)[1].strip() if out.upper().startswith("CLARIFY:") else None


def run_team(chat_id, task, agent_names=None, allow_tools=None, sources=None):
    """Run multiple agents IN PARALLEL on the same task, stream their interleaved
    steps, then EITHER ask the user one clarifying question (if the input was
    ambiguous) OR synthesize one concise conclusion."""
    names = [n for n in (agent_names or specialist_agents()) if n in AGENTS.all()]
    if not names:
        names = specialist_agents()
    allow = set(allow_tools) if allow_tools else None

    user_msg = task                                   # what the user actually typed this turn
    pend = CLARIFY_PENDING.pop(chat_id, None)
    skip_clarify = bool(pend)
    if pend:                                          # this message answers our clarifying question
        task = f"{pend['task']}\n\nUser clarification: {user_msg}"

    history = TEAM_SESSIONS.setdefault(chat_id, [])
    context = ""
    if history:
        context = ("Earlier in this investigation:\n" +
                   "\n".join(f"- Q: {h['task']}\n  Conclusion: {h['synthesis'][:300]}"
                             for h in history) + "\n\n")
    scope = ""
    if sources:
        scope = ("Use ONLY these data sources, tables, and documents: "
                 f"{', '.join(sources)}. Ignore any not listed.\n\n")
    prompt = context + scope + task

    runs.start_run(chat_id, "team")
    def emit(ev):
        runs.record(chat_id, ev)
        return ev

    yield emit({"type": "user_message", "data": {"text": user_msg}})

    # Route: pick only the specialists relevant to this question (not blind fan-out).
    candidates = names
    names = _route_agents(task, names)
    skipped = [n for n in candidates if n not in names]
    yield emit({"type": "agent_switch",
                "data": {"agent": "team", "role": "dispatch", "agents": names,
                         "skipped": skipped, "chat_id": chat_id}})

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

    # If the input was ambiguous, ask the user ONE clarifying question instead of
    # guessing past the specialists who flagged it.
    if len(names) > 1 and not skip_clarify:
        cq = _needs_clarification(task, results)
        if cq:
            CLARIFY_PENDING[chat_id] = {"task": task}
            yield emit({"type": "needs_human", "data": {"question": cq, "chat_id": chat_id}})
            runs.finish_run(chat_id, "awaiting_human")
            return

    # One agent selected -> return its findings directly; 2+ -> synthesize across them.
    if len(names) == 1:
        synthesis = list(results.values())[0] or "(no findings)"
    else:
        synthesis = _synthesize(task, results)
    history.append({"task": task, "synthesis": synthesis})
    runs.finish_run(chat_id, "done")
    yield emit({"type": "final", "data": {"message": synthesis, "chat_id": chat_id, "synthesis": True}})
    try:
        sg = suggest_questions(f"Question: {user_msg}\nConclusion: {synthesis[:400]}")
        yield emit({"type": "suggestions", "data": {"questions": sg}})
    except Exception:
        pass


def _synthesize(task, results):
    """One brief conclusion from the parallel specialists. The full per-specialist
    detail is in the trace, so we do NOT dump it here (that was the verbosity)."""
    findings = "\n\n".join(f"{n}: {r}" for n, r in results.items())
    if cfg.mock_llm:
        return "Combined findings:\n" + "\n".join(f"- {n}: {(r or '')[:140]}" for n, r in results.items())
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"Question: {task}\n\nSpecialist findings:\n{findings}\n\n"
              "Answer the question in at most 5 sentences or one small table. Give the "
              "single most likely cause only if relevant. Cite the table.column or "
              "document behind each point. Do NOT repeat the specialists' full text and "
              "do NOT add extra sections."}],
            [], _style("You are the lead RCA investigator. Be brief."))
        concl = (r.content or "").strip()
    except Exception:
        concl = ""
    return concl or ("Findings:\n" + "\n".join(f"- {n}: {(r or '')[:200]}" for n, r in results.items()))


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
