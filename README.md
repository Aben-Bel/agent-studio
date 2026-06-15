# Joke Platform

A small, complete demo of the team architecture: a backend with auto-discovered
agents, tools, skills, and connectors, and a React wizard frontend that talks to
it over a stable API. A joke agent uses a tool (gets a joke from your dataset), a
skill (punches it up in persona), and a connector (CSV + document search). It runs
fully offline; flip one env var to use AWS Bedrock.

## Run

Backend (terminal 1):
```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt
cp .env.template .env          # MOCK_LLM=1 means offline, no AWS needed
bash run_backend.sh            # seeds data, serves on http://localhost:8000
```
Swagger for the UI team: http://localhost:8000/docs

Frontend (terminal 2):
```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173 (proxies /api to :8000)
```

## The wizard
1. Add data: upload a joke CSV and policy/manual .txt files.
2. Create agent: write a persona, pick which tools/skills it may use. This
   registers a live custom agent.
3. Chat: ask for a joke and watch the orchestrator feed show every step
   (agent routed, tool called, skill run, final answer).

## How 8 people extend it, with no collisions
Everything is a self-declaring file, auto-discovered at startup. No shared
registry file to edit.

Add a tool -> `tools/anything.py`:
```python
from pydantic import BaseModel
from core.declare import tool
class Args(BaseModel):
    topic: str
@tool("dad_joke", "Return a dad joke about a topic.", Args)
def dad_joke(topic): ...
```

Add a skill -> `skills/anything.py`:
```python
from core.declare import skill
@skill("translate_joke", "Translate a joke to another language.")
def translate_joke(text, lang): ...
```

Add an agent -> `agents/anything.py`:
```python
from core.declare import agent
@agent(name="roaster", description="Friendly roast jokes.",
       tools=["get_random_joke", "punch_up"])
def roaster(ctx):
    return "You are a friendly roast comedian. Keep it kind."
```

Drop the file, restart, and it appears in `/capabilities`, the orchestrator
routes to it, and the frontend shows it. Nobody edits anyone else's file.

## The API contract (what the UI team builds against)
- `GET /capabilities` - auto-discovered agents, tools, skills
- `POST /upload` - CSV -> SQL table, TXT/MD -> searchable docs
- `POST /agents` - create a custom agent from a persona
- `POST /run` - run an agent, streams orchestrator events (SSE)
- `GET /health`
- `GET /docs` and `/openapi.json` - the generated Swagger spec

Streamed event types: `agent_switch`, `progress`, `tool_call`, `tool_result`,
`final`, `error` (see the `Event` model in the spec).

## Stack notes
- `core/model.py` runs an offline mock that emulates a tool-using model so the
  whole demo works with no network. Set `MOCK_LLM=0` plus AWS creds to call
  Bedrock `converse` (verify the Bedrock tool-use path on your account).
- `connectors/memory.py` is keyword search (offline). Swap this one module for a
  vector store on AWS without touching any tool.
- A database link is just a different connection string into the same SQL store
  in `connectors/datastore.py`.
- Everything is local-first and lives in git, so the 72-hour Workshop Studio
  account being wiped costs you only the runtime.

## Layout
```
core/        contract: discovery, registry, declare, orchestrator, model, schemas
agents/      one self-declaring file per agent
tools/       one self-declaring file per tool
skills/      one self-declaring file per skill
connectors/  datastore (SQL), memory (RAG), ingest (routing)
api/         FastAPI -> generates Swagger
frontend/    React + Vite wizard (upload -> persona -> chat)
data/        sample joke dataset, manual, policy
scripts/     seed.py
```
