"""Platform introspection: what the system can do, and the audit trail."""
from fastapi import APIRouter

from core import orchestrator, runs
from core.schemas import Capabilities, Event

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/capabilities", response_model=Capabilities)
def capabilities():
    """Everything the system can do right now, generated from the registries:
    agents, tools (with version/owner), skills, MCP servers, and pipeline stages.
    Human-readable description/limits ship as {en, de} pairs so the UI switches
    language with zero refetch. New capabilities appear here with no code change."""
    return orchestrator.capabilities()


@router.post("/translate")
def translate(req: dict):
    """On-demand translation for the language toggle. The orchestrator no longer eagerly
    translates every event to the OTHER language (that per-event LLM call was the dominant
    per-turn latency); the frontend instead asks here only for the texts it needs, only
    when the user actually switches language. Body: {texts: [...], lang: 'de'|'en'}.
    Returns {translations: [...]} aligned to `texts`; any failure falls back to the source."""
    from core import model
    texts = (req or {}).get("texts") or []
    lang = (req or {}).get("lang") or "en"
    out = []
    for tx in texts:
        try:
            out.append(model.translate(tx, lang))
        except Exception:
            out.append(tx)
    return {"translations": out}


@router.get("/suggest")
def suggest(lang: str = "en"):
    """A few data-aware starter questions so the user is not staring at a blank box.
    `lang` (URL-derived, untrusted) selects the question language; anything other
    than a known code falls back to English defaults inside suggest_questions."""
    return {"questions": orchestrator.suggest_questions(lang=lang)}


@router.get("/runs")
def list_runs():
    """The investigation audit trail: every run, its agent, status, and step count."""
    return {"runs": runs.list_runs()}


@router.get("/runs/{chat_id}")
def get_run(chat_id: str):
    """Full, replayable trace of one investigation - every step persisted."""
    return runs.get_run(chat_id)


# Surfaces the Event schema in OpenAPI so the UI team sees the streamed shape.
@router.get("/event-schema", response_model=Event)
def event_schema():
    return {"type": "progress", "data": {"message": "example"}}
