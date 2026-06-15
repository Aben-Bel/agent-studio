from .registry import AGENTS, TOOLS, SKILLS
from . import model
from .config import cfg


def capabilities():
    return {
        "agents": [{"name": a.name, "description": a.description, "tools": a.tools}
                   for a in AGENTS.all().values()],
        "tools": [{"name": t.name, "description": t.description}
                  for t in TOOLS.all().values()],
        "skills": [{"name": s.name, "description": s.description}
                   for s in SKILLS.all().values()],
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
                        "schema": {"type": "object", "properties": {}}})
    return out


def _dispatch(name, args):
    """A failing tool/skill returns an error string; the agent continues."""
    try:
        if name in TOOLS.all():
            t = TOOLS.get(name)
            return str(t.fn(**t.args(**args).model_dump()))
        if name in SKILLS.all():
            return str(SKILLS.get(name).fn(**args))
        return f"unknown function '{name}'"
    except Exception as e:
        return f"ERROR in '{name}': {e}"


def run(agent_name, message, history=None):
    """Generator of events. The orchestrator narrates every step so the UI can
    show what is going on live."""
    agent = AGENTS.get(agent_name)
    system = agent.fn({}) if callable(agent.fn) else ""
    yield {"type": "agent_switch", "data": {"agent": agent.name,
                                             "description": agent.description}}
    msgs = list(history or []) + [{"role": "user", "content": message}]
    funcs = _specs(agent.tools)

    for step in range(cfg.max_steps):
        yield {"type": "progress", "data": {"message": f"reasoning (step {step + 1})"}}
        try:
            r = model.complete(msgs, funcs, system)
        except Exception as e:
            yield {"type": "error", "data": {"message": str(e)}}
            return

        if r.tool_calls:
            msgs.append({"role": "assistant", "tool_calls": r.tool_calls})
            for tc in r.tool_calls:
                kind = "skill" if tc["name"] in SKILLS.all() else "tool"
                yield {"type": "tool_call",
                       "data": {"kind": kind, "name": tc["name"], "args": tc["arguments"]}}
                result = _dispatch(tc["name"], tc["arguments"])
                yield {"type": "tool_result",
                       "data": {"kind": kind, "name": tc["name"], "result": result[:400]}}
                msgs.append({"role": "tool", "name": tc["name"],
                             "tool_call_id": tc["id"], "content": result})
            continue

        yield {"type": "final", "data": {"message": r.content or ""}}
        return

    yield {"type": "final", "data": {"message": "(stopped after max steps)"}}
