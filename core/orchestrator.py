import inspect
import itertools
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
    "- STATISTICAL HONESTY (hard rule): every quantitative claim about defects/yield must "
    "carry n, an effect size, and the adjusted p-value the tool returned. Do NOT use the "
    "words 'cause', 'root cause', 'drives', 'driven by', or 'responsible for' unless a "
    "significance test PASSED and confounders were checked; otherwise say 'associated with' "
    "and state the test result. If a tool returned a 'no significant association' or "
    "'insufficient/degenerate data' result, REPORT THAT NULL plainly — name no culprit and "
    "do not substitute a narrative. A confounded variable must be reported as confounded, "
    "not as a cause.\n"
    "- RESULT KIND IS NOT FUNGIBLE: a tested null (no significant association), an "
    "insufficient/degenerate result, and a target you did NOT analyze are three DIFFERENT "
    "states. Never present a not-analyzed or insufficient target as a tested null. If you "
    "could not analyze a named target (ran out of steps, no scoped result), say 'not "
    "analyzed' and suggest asking it on its own — do not imply it was tested and clean.\n"
    "- For a within-group/within-lot driver question, use a scoped test (e.g. "
    "driver_within_scope with scope={column,values}); do not answer a within-group "
    "question from a whole-table scan.\n"
    "- If something is unknown, missing, or a tool is not implemented, say so in one line.\n"
    "- If the user asks to download, export, save, or get a PDF / slide deck / "
    "presentation / report / document of the findings, CALL the prepare_download tool "
    "(format 'presentation_pdf' for slides/PDF, 'report_md' for a report). You CAN "
    "produce downloadable files - never say you cannot."
)


def _style(base):
    return (STYLE + "\n\n" + base) if base else STYLE


def _with_lang(system, lang):
    """Append a one-line directive telling the agent to answer in the user's
    language. English is the null case (returns system unchanged) so the EN path
    is byte-identical to before - the anti-regression guarantee."""
    if not lang or lang == "en":
        return system
    name = model.LANG_NAME.get(lang)
    if not name:
        return system
    return system + (f"\n\nIMPORTANT: Write your entire response to the user in {name}. "
                     "Keep table.column references, identifiers, numbers, and units exactly "
                     "as in the data.")


# Which data fields of each event type are HUMAN-READABLE PROSE that must flip
# language. Everything not listed (names, ids, formats, numbers, raw tool args)
# stays literal. This is the single source of truth for "every possible text",
# so adding a new event = adding one line here, and no emission site handles i18n.
_TEXT_FIELDS = {
    "user_message":  ["text"],
    "final":         ["message"],
    "needs_human":   ["question"],
    "progress":      ["message"],
    "thinking":      ["text"],
    "error":         ["message"],
    "context_added": ["text"],
    "tool_result":   ["result"],
    "agent_switch":  ["description", "task"],
    "suggestions":   ["questions"],   # a LIST of strings - paired element-wise
}

# Event fields that are DATA/INTERNAL, not user-facing prose: they get a source-side
# pair for back-compat but are NEVER background-translated (a tool result is JSON, a
# thinking trace is internal) — translating them wastes LLM calls for no UI benefit.
_NO_BG_TRANSLATE = {("tool_result", "result"), ("thinking", "text")}


_eid_counter = itertools.count(1)


def _localize(ev, lang, deferrals=None):
    """Pair every human-readable field of an event into {en, de} so the frontend can
    switch language client-side with no re-run. The SOURCE side (the run language) is
    filled instantly; the OTHER side is filled only when cheap (templated phrases), else
    left EMPTY and queued in `deferrals` for background translation after the turn — this
    keeps the per-event LLM translation call off the critical path while preserving the
    full pair (the empty side is patched in later via a `translation_update` event).

    Every paired event gets a stable `eid` so a later translation_update can target it.
    `deferrals` (if given) collects {eid, field, lang(target), text} to translate later.
    Offline (mock) translate is a no-op; failures fall back to source, never blank."""
    fields = _TEXT_FIELDS.get(ev.get("type"))
    if not fields:
        return ev
    d = dict(ev.get("data") or {})
    other = _other(lang)
    paired = False
    for f in fields:
        val = d.get(f)
        if f == "questions":                      # list of strings (agent-produced)
            if not val:
                continue
            # questions are short; translate the cheap static ones, defer the rest as a list
            d["questions_i18n"] = {lang: list(val), other: ["" for _ in val]}
            paired = True
            if deferrals is not None and not cfg.mock_llm:
                deferrals.append({"eid": d.get("eid"), "field": "questions",
                                  "lang": other, "text": list(val)})
        else:
            if not (val or "").strip():
                continue
            d[f + "_i18n"] = _pair(val, lang)
            paired = True
            # Queue the other side for background translation — UNLESS it was filled
            # cheaply already, or this field is data/internal (tool results, thinking).
            if (deferrals is not None and not cfg.mock_llm
                    and not d[f + "_i18n"].get(other)
                    and (ev.get("type"), f) not in _NO_BG_TRANSLATE):
                d.setdefault("eid", None)
                deferrals.append({"field": f, "lang": other, "text": val, "_d": d})
    if paired and not d.get("eid"):
        d["eid"] = f"e{next(_eid_counter)}"
        # back-fill eid into any deferral rows for this event
        for dr in (deferrals or []):
            if dr.get("_d") is d:
                dr["eid"] = d["eid"]
        for dr in (deferrals or []):
            if dr.get("field") == "questions" and dr.get("eid") is None:
                dr["eid"] = d["eid"]
    for dr in (deferrals or []):
        dr.pop("_d", None)
    return {"type": ev["type"], "data": d}


def _drain_translations(chat_id, deferrals):
    """Translate the deferred OTHER-language sides AFTER the answer has been sent, and
    yield a `translation_update` event per item so the frontend patches that message's
    pair in place. Also persists the filled translation onto the recorded event in the
    trail (so a reload has the complete pair). Best-effort: a failure is skipped, never
    blanks. The answer is already on screen — this runs while the user reads it."""
    seen = set()
    for dr in deferrals:
        eid, field, target, text = dr.get("eid"), dr.get("field"), dr.get("lang"), dr.get("text")
        if not eid or field is None:
            continue
        key = (eid, field)
        if key in seen:
            continue
        seen.add(key)
        try:
            if isinstance(text, list):
                filled = [_tr(t, target) for t in text]
            else:
                filled = _tr(text, target)
        except Exception:
            continue
        runs.patch_translation(chat_id, eid, field, target, filled)
        ev = {"type": "translation_update",
              "data": {"eid": eid, "field": field, "lang": target,
                       "text": filled, "chat_id": chat_id}}
        runs.record(chat_id, ev)
        yield ev


def _other(lang):
    return "de" if lang == "en" else "en"


def _pair(text, lang):
    """Build the {en, de} pair for one string. The SOURCE side is filled eagerly (free);
    the OTHER side is translated LAZILY — only templated phrases (static map, no LLM) are
    filled now, real prose is left for on-demand translation when the user actually toggles
    language. This removes a synchronous Bedrock translation call from EVERY streamed event
    on the critical path (the dominant per-turn latency), while losing no feature: the
    frontend falls back to the source side until the other language is fetched, and a user
    on their own language never needed the other side at all.

    src is detected so templated trace lines (always English) still flip via the static map."""
    src = "en" if _is_templated(text) else lang
    other = _other(src)
    other_text = _tr_static(text, other)        # static map only — never an LLM call here
    pair = {src: text}
    if other_text is not None:
        pair[other] = other_text                # cheap templated translation, fill it now
    return pair


# Orchestrator-emitted English templates (always English regardless of run lang).
# Translated by a static map - no LLM call - so high-frequency trace lines are
# cheap and instant. Add a line here when you add a new templated emit string.
_PHRASE_DE = {
    "The agent needs your input.": "Der Agent benötigt Ihre Eingabe.",
    "(stopped after max steps)": "(nach maximalen Schritten gestoppt)",
    "(no findings)": "(keine Erkenntnisse)",
    "(empty)": "(leer)",
    "(no content)": "(kein Inhalt)",
}
_PHRASE_EN = {v: k for k, v in _PHRASE_DE.items()}


def _is_templated(text):
    """True for strings the orchestrator emits verbatim in English (so their
    source language is en, not the run language)."""
    t = (text or "").strip()
    return t in _PHRASE_DE or t.startswith("reasoning (step ")


def _tr_static(text, target_lang):
    """Static-map translation ONLY (no LLM). Returns the translated string for known
    templated phrases / the 'reasoning (step N)' line, else None — signalling the caller
    to defer real-prose translation to on-demand rather than block the run on an LLM call."""
    text = text or ""
    if not text.strip():
        return text
    table = _PHRASE_DE if target_lang == "de" else _PHRASE_EN if target_lang == "en" else {}
    if text in table:
        return table[text]
    if text.startswith("reasoning (step "):
        return (text.replace("reasoning (step ", "Überlegung (Schritt ", 1)
                if target_lang == "de" else text)
    return None


def _tr(text, target_lang):
    """Translate one string to target_lang. Static fast paths first (no LLM call);
    everything else goes through the model translator (a no-op offline). Used by the
    on-demand translation endpoint when the user toggles language."""
    static = _tr_static(text, target_lang)
    if static is not None:
        return static
    return model.translate(text, target_lang)


# Capability strings (descriptions/limits) are STATIC. Their German is PRE-GENERATED
# once into core/caps_i18n_de.json (run: python -m scripts.gen_caps_i18n) and shipped
# in the repo, so serving the catalog makes ZERO model calls - instant, reviewable,
# and immune to the model "obeying" an imperative description instead of translating
# it. Missing/new strings simply fall back to English until the script is re-run.
_CAPS_DE: dict = {}


def _load_caps_de():
    global _CAPS_DE
    if _CAPS_DE:
        return _CAPS_DE
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "caps_i18n_de.json")
    try:
        with open(path, encoding="utf-8") as f:
            _CAPS_DE = json.load(f)
    except Exception:
        _CAPS_DE = {}
    return _CAPS_DE


def _pair_static(text):
    """{en, de} for a fixed English capability string. German comes from the
    pre-generated static map; falls back to English if absent (new/edited string
    not yet regenerated). NEVER calls the model - the catalog stays instant."""
    text = text or ""
    if not text.strip():
        return {"en": "", "de": ""}
    de = _load_caps_de().get(text) or text
    return {"en": text, "de": de}


def capabilities():
    """Capability catalog. Every human-readable description/limits ships BOTH as the
    plain English string (back-compat) AND as a `*_i18n` {en, de} pair, so the UI -
    including tool tooltips - switches language client-side with no refetch and no
    on-the-fly translation. Names/ids/versions stay literal."""
    def entry(d, **extra):
        out = {"description": d, "description_i18n": _pair_static(d)}
        out.update(extra)
        return out
    return {
        "agents": [{"name": a.name, "tools": a.tools, **entry(a.description),
                    # Surface the typed routing metadata so the UI can show WHEN/HOW
                    # to use each agent and what it is/ isn't for. Paired for i18n.
                    "when_to_use": getattr(a.routing, "when_to_use", ""),
                    "when_to_use_i18n": _pair_static(getattr(a.routing, "when_to_use", "")),
                    "how_to_use": getattr(a.routing, "how_to_use", ""),
                    "how_to_use_i18n": _pair_static(getattr(a.routing, "how_to_use", "")),
                    "what_to_use_for": getattr(a.routing, "what_to_use_for", ""),
                    "what_to_use_for_i18n": _pair_static(getattr(a.routing, "what_to_use_for", "")),
                    "what_not_to_use_for": getattr(a.routing, "what_not_to_use_for", ""),
                    "what_not_to_use_for_i18n": _pair_static(getattr(a.routing, "what_not_to_use_for", "")),
                    }
                   for a in AGENTS.all().values()],
        "tools": [{"name": t.name, "version": t.version, "owner": t.owner, "tags": t.tags,
                   "limits": getattr(t, "limits", ""),
                   "limits_i18n": _pair_static(getattr(t, "limits", "")),
                   **entry(t.description)}
                  for t in TOOLS.all().values()],
        "skills": [{"name": s.name,
                    "limits": getattr(s, "limits", ""),
                    "limits_i18n": _pair_static(getattr(s, "limits", "")),
                    **entry(s.description)}
                   for s in SKILLS.all().values()],
        "mcp": [{"name": m.name, "config": m.config, **entry(m.description)}
                for m in MCP.all().values()],
        "stages": [{"name": s.name, "order": s.order, **entry(s.description)}
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


# Result `kind`s that carry a typed statistical verdict worth rolling up per target.
_TYPED_KINDS = {"finding", "no_significant_association", "insufficient_data",
                "incompatible_data"}


def _scope_filters(args):
    """Normalize a tool's `scope` arg into a list of well-formed {column, values}
    filters. Junk entries (bare strings from mocks/garbled calls, missing column)
    are dropped, so every downstream consumer can assume dicts with a column."""
    scope = (args or {}).get("scope")
    if not scope:
        return []
    raw = scope if isinstance(scope, list) else [scope]
    return [f for f in raw if isinstance(f, dict) and f.get("column")]


def _typed_record(name, args, obj):
    """Build a typed per-target record {target, kind, stat, evidence, scope_filters,
    table} from a stats tool's structured result, or None if this result isn't a typed
    verdict. `target` is the scope/group the verdict pertains to (scope label, else the
    table). `scope_filters` (the structured {column, values}) and `table` let the
    roll-up derive the FULL expected target domain from the DATA and mark unreached
    values not_analyzed. Schema-agnostic: reads only generic fields the stats core
    emits."""
    if not isinstance(obj, dict):
        return None
    kind = obj.get("kind")
    if kind not in _TYPED_KINDS:
        return None
    detail = obj.get("detail") if isinstance(obj.get("detail"), dict) else obj
    scope = obj.get("scope") or detail.get("scope_labels") or []
    target = ", ".join(scope) if scope else (args or {}).get("table") or detail.get("table") or "all rows"
    # A compact stat headline pulled from whatever the result exposes.
    stat = (obj.get("summary") or detail.get("reason") or "").strip().splitlines()
    # For the structural null-drill guard: a GROUP scan that flagged sub-groups exposes
    # them in detail.flagged (each a dict with 'group'); record the grouping column +
    # the flagged sub-group VALUES so the roll-up can require a driver test for each.
    is_group_scan = name in ("correlate_params_vs_yield", "compare_process_steps")
    flagged_subgroups = []
    sub_col = detail.get("group_col") or ""
    if is_group_scan and kind == "finding":
        flagged_subgroups = [str(f.get("group")) for f in (detail.get("flagged") or [])
                             if isinstance(f, dict) and f.get("group") is not None]
    return {"scope_filters": _scope_filters(args),
            "table": (args or {}).get("table") or detail.get("table") or "",
            "target": target, "kind": kind, "tool": name,
            "is_group_scan": is_group_scan, "sub_col": sub_col,
            "flagged_subgroups": flagged_subgroups,
            "stat": (stat[-1] if stat else ""), "evidence": obj.get("summary", "")}


# Stats tools that, when SCOPED to a target, are an attempt to analyze THAT target —
# so a scoped call here that errors / returns no verdict means the target was engaged
# but not analyzed (must surface, never vanish). A scoped call to a non-analysis tool
# (e.g. query_data) is not a target verdict attempt and is ignored.
_ANALYSIS_TOOLS = {"correlate_params_vs_yield", "compare_process_steps",
                   "parameter_bin_analysis", "driver_within_scope"}


def _not_analyzed_record(name, args, reason):
    """Typed `not_analyzed` record for a SCOPED analysis call that errored or returned
    no usable verdict, so an engaged-but-unanalyzed target is shown explicitly instead
    of disappearing. Returns None for non-scoped or non-analysis calls (no phantom
    target rows). `not_analyzed` is the lowest-priority kind — a real verdict for the
    same scope supersedes it in the roll-up."""
    if name not in _ANALYSIS_TOOLS:
        return None
    scope_filters = _scope_filters(args)   # already drops junk entries
    if not scope_filters:
        return None                  # only ENGAGED (scoped) targets get a row
    labels = []
    for f in scope_filters:
        c, v = f.get("column"), f.get("values")
        v = v if isinstance(v, (list, tuple, set)) else [v]
        labels.append(f"{c}={'|'.join(map(str, v))}")
    # is_group_scan=False so a not_analyzed (even from a failed group-scan tool) is a
    # HEADLINE candidate for the target, not treated as intermediate group evidence —
    # it has no flagged sub-groups to contribute, and a real verdict still supersedes it.
    return {"scope_filters": scope_filters,
            "table": (args or {}).get("table") or "",
            "target": ", ".join(labels), "kind": "not_analyzed", "tool": name,
            "is_group_scan": False,
            "sub_col": "", "flagged_subgroups": [],
            "stat": "", "evidence": (reason or "")[:200]}


def _dispatch(name, args, sink=None):
    """A failing tool/skill returns an error string; the agent continues.
    When `sink` (a list) is given, a typed per-target record is appended for any
    stats tool that returned a structured verdict — preserving the finding/null/
    insufficient distinction UNFLATTENED for the per-target roll-up, while the agent
    still receives the human string."""
    try:
        if name in TOOLS.all():
            t = TOOLS.get(name)
            obj = t.fn(**t.args(**args).model_dump())
            if sink is not None:
                rec = _typed_record(name, args, obj)
                if rec:
                    sink.append(rec)
                else:
                    # Scoped analysis call that produced no typed verdict (string
                    # error / empty result): the target was engaged but not analyzed.
                    na = _not_analyzed_record(name, args, reason=str(obj))
                    if na:
                        sink.append(na)
            return str(obj)
        if name in SKILLS.all():
            fn = SKILLS.get(name).fn
            params = inspect.signature(fn).parameters
            safe = {k: v for k, v in (args or {}).items() if k in params}
            return str(fn(**safe))
        return f"unknown function '{name}'"
    except Exception as e:
        # A scoped analysis call that raised: still surface the engaged target as
        # not_analyzed rather than letting it vanish.
        if sink is not None:
            na = _not_analyzed_record(name, args, reason=f"error: {e}")
            if na:
                sink.append(na)
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
           "pending": None, "step": 0, "inbox": [], "sub": True,
           "lang": parent_sess.get("lang", "en")}
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
            r = model.complete(sess["msgs"], funcs, _with_lang(sess["system"], sess.get("lang", "en")))
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
                    # Typed stats verdicts are collected on the session for the
                    # per-target roll-up (Option C) - unflattened alongside the string.
                    result = _dispatch(name, tc["arguments"], sess.setdefault("typed", []))

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
        msg = r.content or ""
        yield {"type": "final", "data": {"message": msg, "chat_id": sess["chat_id"]}}
        return

    sess["status"] = "done"
    sess["step"] = 0
    yield {"type": "final",
           "data": {"message": "(stopped after max steps)", "chat_id": sess["chat_id"]}}


def start_or_resume(chat_id, agent_name, message, allow_tools=None, sources=None, lang="en"):
    """Stateful entry point used by the API. Starts a new chat or continues an
    existing one by chat_id. The human's `message` either opens a new turn or
    answers a pending `ask_human` pause. Optional tool/source restrictions scope
    the run, matching the team mode. `lang` adds a {en, de} `text_i18n` pair to
    user-facing events so the frontend can switch language with no re-run; the
    single agent is told to answer in `lang`."""
    sess = SESSIONS.get(chat_id)
    if sess is None:
        sess = _new_session(chat_id, agent_name)
        sess["allow_tools"] = set(allow_tools) if allow_tools else None
        sess["lang"] = lang
        sess["sources"] = sources        # remember the run's data scope across resume turns
        runs.start_run(chat_id, agent_name)
        agent = AGENTS.get(agent_name)
        ev = _localize({"type": "agent_switch",
                        "data": {"agent": agent.name, "description": agent.description,
                                 "chat_id": chat_id}}, lang)
        runs.record(chat_id, ev)
        yield ev
    sess["lang"] = lang   # honour the language chosen for THIS turn

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
        ev = _localize({"type": "user_message", "data": {"text": message}}, lang)
        runs.record(chat_id, ev)
        yield ev

    # Every streamed event is persisted to the audit trail (full visibility).
    # _localize pairs each event's text into {en, de}; the SOURCE side renders now, the
    # OTHER side is deferred to background translation (drained after the answer) so no
    # translation LLM call blocks the run.
    # Enforce the run's data scope so every tool the agent calls only sees the
    # user's selected sources/documents (set on this thread for the _drive loop).
    from connectors import scope as _scope
    _scope.set_scope(sess.get("sources"))
    deferrals = []
    try:
        for ev in _drive(sess):
            # Tie each claim in the answer to the tool result that supports it (and keep
            # only the cited evidence) BEFORE localisation, so the superscript markers are
            # part of the {en,de} text pair and the references are verifiable per claim.
            if ev.get("type") == "final" and not ev.get("data", {}).get("depth"):
                try:
                    from core.report import turn_references, cite_conclusion
                    msg, refs = cite_conclusion(ev["data"].get("message", ""),
                                                turn_references(chat_id))
                    ev["data"]["message"] = msg
                    ev["data"]["references"] = refs
                except Exception:
                    pass
            ev = _localize(ev, lang, deferrals)
            runs.record(chat_id, ev)
            yield ev
        # Answer is shown; fill the deferred other-language sides in the background.
        for tu in _drain_translations(chat_id, deferrals):
            yield tu
    finally:
        _scope.clear_scope()
    runs.finish_run(chat_id, sess["status"])


def specialist_agents():
    """Agents meant to be run as a team (everyone except supervisors that recruit)."""
    return [n for n, a in AGENTS.all().items() if CONSULT_TOOL not in (a.tools or [])]


TEAM_SESSIONS: dict = {}    # chat_id -> [{"task", "synthesis"}] for follow-up continuity
CLARIFY_PENDING: dict = {}  # chat_id -> {"task"} when the team asked the user to clarify


def suggest_questions(context="", lang="en"):
    """A few short questions to help the user (initial starters, or follow-ups).
    Data-aware: knows what tables/documents are loaded. Returns <= 4 questions.
    `lang` makes the questions come out in the user's language."""
    from connectors import datastore, memory
    tables = [t for s in datastore.list_sources() for t in s["tables"]]
    docs = [d["source"] for d in memory.list_documents()]
    fallback_en = ["What can you do?",
                   "Which process step has the most defects?",
                   "What is the top defect driver?"]
    fallback_de = ["Was kannst du tun?",
                   "Welcher Prozessschritt hat die meisten Defekte?",
                   "Was ist der Hauptverursacher von Defekten?"]
    fallback = fallback_de if lang == "de" else fallback_en
    if cfg.mock_llm:
        return fallback
    info = f"Loaded tables: {', '.join(tables) or 'none'}. Documents: {', '.join(docs) or 'none'}."
    sys = _with_lang(
        "You suggest concise, useful NEXT QUESTIONS the user could ask. Output ONLY the "
        "questions, exactly one per line. Each must be a single short question (3-9 words) "
        "ending with '?'. NEVER write an answer, explanation, analysis, code, table, "
        "markdown, headings, or emojis. Do not number or quote them.", lang)
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"{info}\n{context}\n\nSuggest 3 short, specific questions a yield-analysis "
              "engineer might ask next given this data. Each a single question under 9 words."}],
            [], sys)
        qs = [_clean_suggestion(ln) for ln in (r.content or "").splitlines()]
        qs = [q for q in qs if _is_question(q)][:4]
        return qs or fallback
    except Exception:
        return fallback


def _clean_suggestion(line):
    """Strip list/quote decoration from one suggestion line."""
    return (line or "").strip().strip("-*•0123456789. \t\"'")


def _is_question(q):
    """Keep ONLY genuine short questions - reject answers/markdown/code/prose that
    the model sometimes returns instead of a question (the bug that put a full
    analysis into a 'Try asking' chip)."""
    if not q:
        return False
    # Reject any markdown / code / table / heading / emoji markers, and multi-clause prose.
    if any(ch in q for ch in ("`", "#", "|", "*", "{", "}", "(", ")", "\\")):
        return False
    if any(ord(ch) > 0x2400 for ch in q):          # emoji / symbol block -> not a plain question
        return False
    if len(q) > 90 or q.count(" ") > 12:           # too long to be a starter question
        return False
    if q.count(".") > 1 or ":" in q:               # looks like a sentence/answer, not a question
        return False
    return q.endswith("?")


def _always_on(names):
    """Agents that declare themselves cross-cutting (routing.always) — kept in EVERY
    run regardless of the LLM's pick. Read by PROPERTY, never by name, so any agent can
    opt in by setting always=True and the orchestrator stays agent-agnostic."""
    return [n for n in names if getattr(AGENTS.get(n).routing, "always", False)]


def _route_agents(task, names):
    """LLM picks the minimal set of relevant specialists for THIS question, from
    the ones the user selected. Routing, not always fan-out. Falls back to all.

    Agents flagged `routing.always` (cross-cutting, e.g. intake/readiness) are kept in
    the result whether or not the LLM lists them — advisory routing text alone does not
    reliably retain them."""
    must = _always_on(names)
    if len(names) <= 1 or cfg.mock_llm:
        return names
    catalog = "\n".join(f"- {n}: {AGENTS.get(n).routing_text()}" for n in names)
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"Question: {task}\n\nAvailable specialists:\n{catalog}\n\n"
              "List ONLY the specialist names actually needed to answer THIS question, "
              "comma-separated. Omit irrelevant ones. Always include any specialist marked "
              "'ALWAYS run this'. If genuinely unsure, include it."}],
            [], _style("You route a question to the minimal set of relevant specialists."))
        picked = (r.content or "").replace("\n", ",").lower()
        sel = [n for n in names if n.lower() in picked]
        # Force-keep cross-cutting agents the LLM may have pruned, preserving order.
        sel = [n for n in names if n in sel or n in must]
        return sel or names
    except Exception:
        return names


def _maybe_ambiguous(task):
    """Cheap pre-filter: could this question even BE ambiguous enough to warrant a
    clarify round-trip? Skips the LLM clarify call on the common case (a specific,
    self-contained question) and only spends it when the input contains a bare,
    context-free identifier/number the specialists might have had to guess at.

    Conservative: when unsure, returns True (run the gate) so we never lose a genuine
    clarification — this only removes the call for clearly-unambiguous questions."""
    import re
    t = (task or "").strip()
    # A bare standalone number/code (e.g. '844', 'L7') with little surrounding context
    # is the classic ambiguous case the gate exists for.
    bare_token = re.search(r'(?<![\w.])[A-Za-z]?\d{2,}(?![\w.%])', t)
    if bare_token:
        return True
    # Very short questions carry little context -> keep the gate.
    if len(t.split()) <= 4:
        return True
    return False


def _needs_clarification(task, results):
    """LLM decides (not hardcoded) whether the specialists flagged the input as
    ambiguous such that ONE question to the user would materially change the answer.
    Returns the question, or None."""
    if not _maybe_ambiguous(task):
        return None                       # specific, self-contained question -> no round-trip
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


def run_team(chat_id, task, agent_names=None, allow_tools=None, sources=None, lang="en"):
    """Run multiple agents IN PARALLEL on the same task, stream their interleaved
    steps, then EITHER ask the user one clarifying question (if the input was
    ambiguous) OR synthesize one concise conclusion.

    `lang` is the UI language: the investigation runs once and its user-facing
    text (echoed question, clarifying question, synthesis, suggestions) is emitted
    with a `text_i18n` {en, de} pair so the frontend can switch language with no
    re-run. Internals (tool calls, per-agent reasoning) are not translated."""
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
    deferrals = []     # other-language translations to fill in the background after the turn
    def emit(ev):
        # Single chokepoint: pair EVERY event's text into {en, de}. The SOURCE side is
        # filled instantly; the OTHER side is queued in `deferrals` and translated AFTER
        # the answer is sent (see _drain_translations) so no translation LLM call sits on
        # the critical path. The frontend renders the source side now and patches the
        # other side from translation_update events.
        ev = _localize(ev, lang, deferrals)
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
    typed_records = []            # Option C: typed per-target verdicts across all agents
    stopped_short = set()         # agents that hit max_steps (their targets may be unreached)

    def work(name):
        # Scope is thread-local: set it INSIDE each agent's worker thread so every data
        # tool that agent calls only sees the user's selected sources/documents.
        from connectors import scope as _scope
        _scope.set_scope(sources)
        try:
            agent = AGENTS.get(name)
            system = _style(agent.fn({}) if callable(agent.fn) else "")
            sub = {"chat_id": chat_id, "agent": name, "system": system,
                   "msgs": [{"role": "user", "content": prompt}], "status": "running",
                   "pending": None, "step": 0, "inbox": [], "allow_tools": allow,
                   "no_pause": True, "lang": lang, "sub": True, "typed": []}
            q.put({"type": "agent_switch",
                   "data": {"agent": name, "role": "working", "depth": 1, "agent_scope": name}})
            final = ""
            for ev in _drive(sub):
                d = dict(ev["data"]); d["agent_scope"] = name; d["depth"] = 1
                q.put({"type": ev["type"], "data": d})
                if ev["type"] == "final":
                    final = ev["data"].get("message", "")
            results[name] = final
            if "(stopped after max steps)" in (final or ""):
                stopped_short.add(name)
            for rec in sub.get("typed", []):
                typed_records.append({**rec, "agent": name})
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
            CLARIFY_PENDING[chat_id] = {"task": task, "lang": lang}
            yield emit({"type": "needs_human",
                        "data": {"question": cq, "chat_id": chat_id}})
            runs.finish_run(chat_id, "awaiting_human")
            return

    # Per-target roll-up table (Option C): one row per analyzed target with its typed
    # kind, plus an explicit not_analyzed row for any target named in the question that
    # produced no verdict (and a budget note when an agent hit max_steps). Rendered
    # ABOVE the synthesized prose so a finding / genuine null / not-analyzed never blur.
    rollup = _rollup_table(task, typed_records, bool(stopped_short))

    # One agent selected -> return its findings directly; 2+ -> synthesize across them.
    if len(names) == 1:
        synthesis = list(results.values())[0] or "(no findings)"
    else:
        synthesis = _synthesize(task, results, lang)
    if rollup:
        synthesis = rollup + "\n\n" + synthesis
    history.append({"task": task, "synthesis": synthesis})
    # Citable evidence for THIS turn: the exact tool calls + real results behind the
    # answer. Each claim is tied to the specific result that supports it (deterministic
    # token match), and only the references actually USED are kept — so the modal shows
    # provenance for the words, not every tool that happened to run.
    try:
        from core.report import turn_references, cite_conclusion
        synthesis, references = cite_conclusion(synthesis, turn_references(chat_id))
    except Exception:
        references = []
    runs.finish_run(chat_id, "done")
    yield emit({"type": "final",
                "data": {"message": synthesis, "chat_id": chat_id, "synthesis": True,
                         "references": references}})
    try:
        # Feed the FULL conclusion (not a 400-char clip): the answer often names the exact
        # tables/columns the next question should reference (e.g. "wafer_defects has
        # temperature_c, pressure_torr, ..."), and truncating cut those off, leaving the
        # suggester to guess. Cap generously to bound prompt size on very long reports.
        sg = suggest_questions(f"Question: {user_msg}\nConclusion: {synthesis[:2000]}", lang)
        yield emit({"type": "suggestions", "data": {"questions": sg}})
    except Exception:
        pass

    # The answer is already on the user's screen. Now fill the deferred other-language
    # sides in the background and stream translation_update events so a language toggle
    # is seamless — without ever having blocked the answer on a translation call.
    for tu in _drain_translations(chat_id, deferrals):
        yield tu


_KIND_LABEL = {"finding": "finding", "no_significant_association": "genuine null",
               "insufficient_data": "insufficient", "incompatible_data": "incompatible",
               "not_analyzed": "not analyzed",
               "incomplete": "incomplete (driver test pending)"}


def _primary_axis_value(record, axis):
    """The value of the primary scope axis (e.g. lot_id) for a record, or None."""
    for f in record.get("scope_filters") or []:
        if f.get("column") == axis:
            vals = f.get("values")
            vals = vals if isinstance(vals, (list, tuple, set)) else [vals]
            return str(vals[0]) if vals else None
    return None


def _subgroup_value(record, sub_col):
    """The sub-group value (the scoped sub-group column=value) a driver record used."""
    if not sub_col:
        return None
    for f in record.get("scope_filters") or []:
        if f.get("column") == sub_col:
            vals = f.get("values")
            vals = vals if isinstance(vals, (list, tuple, set)) else [vals]
            return str(vals[0]) if vals else None
    return None


def _null_drill_incomplete(target_records, axis):
    """STRUCTURAL null-drill guard (code, not prompt). For one target's records:
    if a GROUP scan FLAGGED a sub-group but NO driver_within_scope record exists for
    that same sub-group, the target is NOT a clean null — it is `incomplete` with a
    driver test still pending. Returns the list of flagged-but-undrilled sub-group
    names (empty => no gap). Schema-agnostic: uses the grouping column the scan
    itself reported."""
    flagged = {}          # sub_col -> set(flagged sub-group values)
    drilled = set()       # (sub_col, value) pairs a driver record covered
    for r in target_records:
        if r.get("is_group_scan") and r.get("flagged_subgroups"):
            sc = r.get("sub_col") or "?"
            flagged.setdefault(sc, set()).update(r["flagged_subgroups"])
        if r.get("tool") == "driver_within_scope":
            for f in r.get("scope_filters") or []:
                c = f.get("column")
                if not c or c == axis:
                    continue
                vals = f.get("values")
                vals = vals if isinstance(vals, (list, tuple, set)) else [vals]
                for v in vals:
                    drilled.add((c, str(v)))
    undrilled = []
    for sc, vals in flagged.items():
        for v in vals:
            if (sc, v) not in drilled:
                undrilled.append(f"{sc}={v}")
    return undrilled


def _rollup_table(task, typed_records, any_stopped_short):
    """Render the typed per-target verdicts as a compact table — ONE row per target
    the run actually ENGAGED (scoped a tool to), with its verdict. An engaged target
    that produced no usable verdict is shown `not_analyzed`. Data values the run never
    engaged get NO row (we do not enumerate the datastore — that produced false
    not_analyzed rows on single-target questions). The INCOMPLETE banner fires ONLY on
    a real signal: an `incomplete` target (flagged-but-undrilled), an engaged
    `not_analyzed` target, or a real truncation. Returns '' when there's nothing to
    report.

    Schema-agnostic, decomposition-free (no Option B), no question parsing: the target
    set is exactly the scope values the records engaged."""
    if not typed_records and not any_stopped_short:
        return ""

    from collections import defaultdict
    # The multi-target axis = the scope column with the most distinct values ENGAGED.
    cv = defaultdict(set)
    for r in typed_records:
        for f in r.get("scope_filters") or []:
            if f.get("column"):
                vals = f.get("values")
                vals = vals if isinstance(vals, (list, tuple, set)) else [vals]
                cv[f["column"]].update(map(str, vals))
    axis = max(cv, key=lambda c: len(cv[c])) if cv else None

    # Group records by engaged axis value (the scoped column=value). A record with no
    # axis filter (whole-table scan) groups under None and never becomes a target row of
    # its own unless it is the only thing there.
    # `not_analyzed` is the LOWEST priority: any real verdict for the same engaged
    # scope supersedes it (error-then-success shows one row, the success).
    rank = {"finding": 4, "incomplete": 3, "no_significant_association": 2,
            "insufficient_data": 1, "incompatible_data": 0, "not_analyzed": -1}
    by_axis = defaultdict(list)
    for r in typed_records:
        av = _primary_axis_value(r, axis) if axis else None
        by_axis[av].append(r)

    resolved = []     # ordered list of (label, kind, stat)
    for av, recs in by_axis.items():
        # The HEADLINE verdict comes from driver / within-scope records (the actual
        # parameter-level answer). A bare GROUP scan flags a sub-group (a step) but is
        # only intermediate evidence — it is not the target's headline.
        headline_recs = [r for r in recs if not r.get("is_group_scan")]
        if av is not None:
            label = f"{axis}={av}"
        elif headline_recs or recs:
            label = (headline_recs or recs)[0].get("target") or "all rows"
        else:
            continue
        if headline_recs:
            best = max(headline_recs, key=lambda r: rank.get(r["kind"], -1))
            kind, stat = best["kind"], (best.get("stat") or "")
        else:
            gs = max(recs, key=lambda r: rank.get(r["kind"], -1))
            if gs.get("flagged_subgroups"):
                kind, stat = "incomplete", ""        # step flagged, never drilled
            else:
                kind, stat = gs["kind"], (gs.get("stat") or "")
        # STRUCTURAL null-drill guard: a target may not be a clean null/insufficient
        # while a flagged sub-group was never drilled. Override to `incomplete`.
        if kind in ("no_significant_association", "insufficient_data", "incomplete"):
            undrilled = _null_drill_incomplete(recs, axis)
            if undrilled:
                kind = "incomplete"
                stat = ("flagged but not drilled: " + ", ".join(undrilled)
                        + " — run the driver test scoped to this sub-group before "
                        "concluding null")
        resolved.append((label, kind, stat))

    # Banner fires ONLY on a real incompleteness signal — never merely because the
    # datastore has other values. (a) any engaged target incomplete/not_analyzed,
    # (b) a real truncation.
    any_incomplete = any(k in ("incomplete", "not_analyzed") for _, k, _ in resolved)
    show_banner = any_incomplete or any_stopped_short

    lines = []
    if show_banner:
        lines.append("> **⚠ INCOMPLETE — not all requested targets were fully analyzed.** "
                     "*incomplete* rows have a flagged sub-group whose driver test is still "
                     "pending; *not analyzed* targets were not tested. Neither is a null — "
                     "re-ask those targets to finish them.")
        lines.append("")
    lines.append("Per-target results (kind = finding / genuine null / insufficient / "
                 "incomplete / not analyzed):")
    for label, kind, stat in resolved:
        klabel = _KIND_LABEL.get(kind, kind)
        stat = (stat or "").strip()
        lines.append(f"- {label}: **{klabel}**" + (f" — {stat}" if stat else ""))
    if any_stopped_short:
        lines.append("- (an analyst hit its step budget; requested targets not listed above "
                     "were not reached — re-ask them individually)")
    return "\n".join(lines)


def _synthesize(task, results, lang="en"):
    """One brief conclusion from the parallel specialists. The full per-specialist
    detail is in the trace, so we do NOT dump it here (that was the verbosity).
    `lang` makes the conclusion come out in the user's language natively (the
    other language is translated downstream for the {en, de} pair)."""
    findings = "\n\n".join(f"{n}: {r}" for n, r in results.items())
    if cfg.mock_llm:
        return "Combined findings:\n" + "\n".join(f"- {n}: {(r or '')[:140]}" for n, r in results.items())
    answer_lang = "" if lang == "en" else f" Write your entire answer in {model.LANG_NAME.get(lang, 'English')}."
    try:
        r = model.complete(
            [{"role": "user", "content":
              f"Question: {task}\n\nSpecialist findings:\n{findings}\n\n"
              "Answer the question in at most 5 sentences or one small table. Give the "
              "single most likely cause only if relevant. Cite the table.column or "
              "document behind each point. Do NOT repeat the specialists' full text and "
              "do NOT add extra sections.\n"
              "CRITICAL: preserve each result's KIND. A 'genuine null' (tested, no "
              "significant association), an 'insufficient' result, and a 'not analyzed' "
              "target are DIFFERENT — never merge them or present a not-analyzed/"
              "insufficient target as if it were a tested null. If a target was not "
              "analyzed, say so and suggest re-asking it on its own."}],
            [], _style("You are the lead RCA investigator. Be brief." + answer_lang))
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
def run(agent_name, message, history=None, lang="en"):
    agent = AGENTS.get(agent_name)
    system = _style(agent.fn({}) if callable(agent.fn) else "")
    sess = {"chat_id": None, "agent": agent_name, "system": system,
            "msgs": list(history or []) + [{"role": "user", "content": message}],
            "status": "running", "pending": None, "step": 0, "inbox": [], "lang": lang}
    yield {"type": "agent_switch",
           "data": {"agent": agent.name, "description": agent.description}}
    yield from _drive(sess)
