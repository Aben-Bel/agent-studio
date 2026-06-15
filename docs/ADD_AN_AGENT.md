# Add an Agent — Team Guide

An **agent** = a persona (system prompt) + a list of **tools/skills** it may call.
Each is a **self-declaring file, auto-discovered on startup**. Work in your **own
subfolder** (`tools/<you>/…`, `agents/<you>/…`) — you never edit a shared file, so
nobody collides. Real example to copy: [agents/rca_assistant.py](../agents/rca_assistant.py).

Below is a tiny end-to-end example: a **tool** + a **skill** + an **agent** that uses both.

---

## 1. Add a tool — `tools/<you>/get_tip.py`
Tools have **typed inputs** (a pydantic model = signature + JSON schema the model sees).

```python
from pydantic import BaseModel
from core.declare import tool

class TipArgs(BaseModel):
    topic: str                      # what to give a tip about

@tool("get_tip", "Return one practical tip about a topic.", TipArgs, owner="you")
def get_tip(topic):
    return f"Tip about {topic}: measure twice, cut once."   # return a string
```

## 2. (optional) Add a skill — `skills/<you>/punch_up.py`
A skill is a reusable routine the agent invokes. Use a skill for multi-step text work;
use a **tool** when you need required, structured inputs.

```python
from core.declare import skill

@skill("punch_up", "Rewrite the given `text` to be punchier, in the given `style`.")
def punch_up(text, style=""):
    return f"[{style}] {text.strip()} — but make it pop!"
```
> ⚠️ Skills don't publish a typed schema, so the model infers args from your
> **description** — name the inputs in it (here: `text`, `style`). If a step needs
> guaranteed structured inputs, make it a `@tool` instead.

## 3. Add the agent — `agents/<you>/coach.py`
List the tool/skill **names** it may use; the function returns the **system prompt**.

```python
from core.declare import agent

@agent("coach", "Gives a tip and rewrites it with energy.",
       tools=["get_tip", "punch_up", "ask_human"])   # tool + skill + built-in names
def coach(ctx):
    return ("You are an upbeat coach. Use get_tip to fetch a tip, then punch_up to "
            "rewrite it in an energetic style. Ask the human (ask_human) if unsure.")
```

---

## 4. Run & test locally

**One-time setup**
```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt
python -m scripts.seed                      # loads the sample dataset
```

**Run the backend** (auto-reloads *and* re-discovers your files on every save)
```bash
uvicorn main:app --reload --port 8000
```
> To use the real model (so the agent actually calls your tools), set `MOCK_LLM=0`
> + AWS creds in `.env`. With `MOCK_LLM=1` it runs offline but only knows the old
> demo flow — it won't drive your new tools.

**Test it**
```bash
# 1. confirm it registered (your agent/tool/skill should appear)
curl -s localhost:8000/capabilities | python -m json.tool

# 2. run it (streams events: tool_call, tool_result, final, …)
curl -N -X POST localhost:8000/run -H 'Content-Type: application/json' \
  -d '{"agent":"coach","message":"give me a tip about welding","history":[]}'
```
Or open **http://localhost:8000/docs** (Swagger) and try `POST /run`.

---

## Checklist
- [ ] File is in your own subfolder (`tools/<you>/`, `agents/<you>/`).
- [ ] `@tool` args are a `BaseModel`; the function params match its fields.
- [ ] The agent's `tools=[...]` names exactly match your `@tool`/`@skill` names.
- [ ] Restart picked it up → it shows in `GET /capabilities`.
- [ ] Tested a `POST /run` with `MOCK_LLM=0` + AWS creds.

## Frontend / Docker note
- The UI auto-shows whatever is in `/capabilities` — no frontend change needed.
- If you run via Docker instead of `uvicorn`, rebuild after adding files:
  `docker compose up -d --build backend`.
