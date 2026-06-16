# Yield Analysis — Root‑Cause Analysis Platform (project overview)

> A multi‑agent, human‑in‑the‑loop **root‑cause analysis platform** for semiconductor
> yield/defect investigation. Built on an **auto‑discovered plugin architecture**: every
> agent, tool, skill, MCP server, pipeline stage and output exporter is a *self‑declaring
> file*, so a whole team extends it in parallel with **no shared files and no merge conflicts**.
> (Internally the package is also called "Agent Studio" — the same engine, data‑agnostic.)

This document describes what the system does, how it's built, and how to run it, so it can
be handed to a reviewer for evaluation.

---

## 1. What it does (user‑facing)

- **Bring your own data**
  - Upload **CSVs** → each becomes its own **SQL table**.
  - Upload **PDF / TXT / MD** → chunked and indexed into a **RAG** (retrieval) store.
  - Connect a **live database URL** (Postgres / MySQL via SQLAlchemy).
  - Direct **browser → S3** upload (presigned) then server‑side ingest.
- **Investigate in natural language** ("Which process step correlates most with yield loss?").
  - **Team mode (default):** runs multiple specialist agents **in parallel** on the same
    question, then synthesizes **one concise conclusion**.
  - **Single‑agent mode:** pick one specialist; stateful, resumable conversation.
  - The lead can **recruit** other specialists mid‑investigation (`consult_agent`).
- **Full visibility / glass‑box:** every step streams live — agent dispatch, reasoning,
  each tool call + its result, data/documents touched — and is **persisted to an audit trail**.
- **Human‑in‑the‑loop:** an agent can **pause to ask the user** (`ask_human`) and resume
  exactly where it stopped; the team can ask **one clarifying question** when the input is
  ambiguous (e.g. a bare id like "844").
- **Add context mid‑run:** type while it works and it's merged on the next step.
- **Export the investigation:** generate a **Markdown report** or **PDF / LaTeX slide deck**
  built from the structured findings (questions, conclusions, the exact tools/queries used
  as evidence).
- **Inspect everything:** preview SQL tables, view uploaded documents, inspect an agent's
  tools, resume any past investigation from the audit trail.
- **UX:** three‑column workspace, **light/dark theme toggle** (glassmorphism), **EN/DE i18n**,
  data‑aware suggested questions, URL‑as‑navigation‑state (refresh/back/deep‑link restore the view).

Observed catalog at runtime (auto‑discovered): **~8 specialist agents**, **~21 tools + skills**,
1 MCP server, 2 pipeline stages, 3 exporters.

---

## 2. Core architectural idea — self‑declaring, auto‑discovered capabilities

The defining design choice. At startup `core.discovery.discover()` **recursively imports**
everything under `agents/ tools/ skills/ mcp/ pipeline/ connectors/ exporters/`. Each file
registers itself via a decorator into a typed registry (`core/registry.py`). Nothing edits a
shared manifest, so N people add capabilities in their own subfolder (`tools/<you>/…`) without
colliding.

Decorators (`core/declare.py`):

| Decorator | Declares | Folder | Appears in |
|---|---|---|---|
| `@agent(name, desc, tools=[...])` | An agent (fn returns its system prompt) | `agents/` | `/capabilities`, orchestrator routing, UI |
| `@tool(name, desc, args, returns=…, version, owner)` | A typed tool (pydantic `args` = JSON schema) | `tools/` | tool catalog, model function‑calling |
| `@skill(name, desc)` | A reusable multi‑step routine (schema inferred) | `skills/` | skill catalog |
| `@mcp(name, …config)` | An MCP server connection | `mcp/` | MCP catalog |
| `@exporter(name, label, ext, media_type, needs=[…])` | An output generator `fn(report)→bytes` | `exporters/` | Download menu |
| `@stage(name, order)` | A document‑processing stage `fn(doc)→doc` | `pipeline/` | ingest pipeline |

Agents can also be created **at runtime from a persona** (the "Add agent" wizard) via
`register_custom_agent(...)` — same contract, no file.

---

## 3. Technology stack

**Backend (Python 3.12)**
- **FastAPI** + **Uvicorn** (ASGI), assembled by an app factory (`api/app.py`); thin routers
  in `api/routers/*` delegate to `core/` services.
- **Pydantic v2** — tool argument/return schemas (→ JSON Schema for function‑calling).
- **SQLAlchemy 2** + **pandas** — datastore; **SQLite** by default (`data/app.db`),
  **psycopg2** for Postgres; MySQL supported via URL.
- **pypdf** — PDF text extraction; **python‑multipart** — uploads.
- **boto3** — **Amazon Bedrock** (Converse API) for the LLM.
- **pytest** — tests.

**LLM layer** (`core/model.py`) — a neutral message/​tool abstraction with two backends:
- **Bedrock Converse** (`MOCK_LLM=0`): default `MODEL_ID=amazon.nova-micro-v1:0`, region
  `eu-central-1` (both configurable; any Bedrock model id works). Converts neutral history to
  Bedrock's strictly‑alternating user/assistant format (coalescing consecutive same‑role turns)
  — this is what makes resumable, mid‑tool‑round conversations work.
- **Offline mock** (`MOCK_LLM=1`, the default): a deterministic stand‑in that *walks each of an
  agent's tools once* and returns a skeleton. Lets the whole app + every agent's wiring run
  with no AWS creds. (It is an emulation of tool use, **not** real reasoning.)

**Frontend**
- **React 18** + **Vite 5** (JSX, no TypeScript).
- **react‑markdown** + **remark‑gfm** for rendering agent output/reports.
- Plain `fetch` API client (`src/api.js`); **SSE** (newline‑delimited JSON) for the streaming run.
- Pure CSS design system with **CSS‑variable tokens**, light/dark themes via `data-theme`
  (see `frontend/DESIGN.md`).

**Infra**
- **Docker** + **docker compose** (backend image + nginx‑served frontend).
- **Terraform** (AWS provider) → single **EC2** host running the compose stack.

---

## 4. Repository layout

```
main.py                 # entrypoint → api.app:app
api/
  app.py                # app factory: discover() → connect env DB → mount routers
  routers/              # capabilities.py · data.py · chat.py · export.py  (thin HTTP layer)
core/
  discovery.py          # recursive auto-import of all capability folders
  registry.py           # typed registries (AGENTS/TOOLS/SKILLS/MCP/STAGES/EXPORTERS)
  declare.py            # the @agent/@tool/@skill/@mcp/@exporter/@stage decorators
  orchestrator.py       # the brain: single-agent + parallel team + recruiting + HITL
  model.py              # Bedrock Converse + offline mock, neutral message format
  runs.py               # audit trail (every event persisted per chat_id)
  report.py / export.py # structured investigation report + export service
  pipeline.py           # runs document stages; config.py · schemas.py · util.py · document.py
agents/                 # data_analyst, equipment_specialist, manuals_expert, rca_assistant,
                        # aneetta/* (yield_quality, analyzer, role_profiles), wuhankui/persona_summarizer
tools/                  # ask_human, consult, data, data_loader, export, pipeline, rag,
                        # rca/{correlate,fmea,stubs}, aneetta/role_supporters
skills/                 # punch_up, aneetta/analyzer, wuhankui/summary_readiness
mcp/filesystem.py       # an MCP server declaration
exporters/              # report_md, presentation_pdf, presentation_tex, _latex
pipeline/               # normalize (order 10) + index (RAG embed)
connectors/             # datastore (SQL), memory (RAG), ingest (routing), s3
data/                   # app.db (SQLite) + sample dataset (wafer defects, fab manual)
scripts/seed.py         # loads the sample dataset
frontend/               # React+Vite app (src/, DESIGN.md, Dockerfile, nginx.conf)
infra/                  # Terraform (main.tf, variables.tf, outputs.tf) + README
docker-compose.yml      # + .override.yml (dev) + .prod.yml
```

---

## 5. Key backend flows

### 5.1 Stateful, resumable single‑agent run  (`start_or_resume`)
1. New `chat_id` → create session, start audit run, emit `agent_switch`.
2. `_drive()` loop (bounded by `MAX_STEPS=8`): call the model with the agent's allowed tool
   schemas **+ always‑injected built‑ins** (`list_data_sources`, `load_uploaded_csv`,
   `prepare_download`) so no agent is ever "data‑blind" or unable to produce a file.
3. For each model tool call → emit `tool_call`, dispatch, emit `tool_result`, append result.
4. `ask_human` → emit `needs_human` and **suspend**; the user's next message becomes that
   tool's result and the loop **resumes from the same point**.
5. No more tool calls → emit `final`. Every event is persisted via `runs.record`.

### 5.2 Parallel team investigation  (`run_team`)
1. `user_message` recorded.
2. **Routing (not blind fan‑out):** an LLM call picks the **minimal relevant subset** of the
   user‑selected specialists for *this* question (falls back to all).
3. Selected agents run **concurrently on threads**, their steps **interleaved** into one stream
   (tagged `depth=1`, `agent_scope`). Parallel agents run with `no_pause` (they can't block the
   others; a missing human input is noted in findings instead).
4. **Clarify gate:** an LLM decides whether the specialists hit a genuinely ambiguous reference;
   if so the team asks the user **one** clarifying question (`needs_human`) and resumes with the
   answer folded into the task.
5. **Synthesis:** one agent → return its findings; 2+ → an LLM **synthesizes a single brief
   conclusion** (full per‑agent detail stays in the trace). Then emits data‑aware follow‑up
   `suggestions`.

### 5.3 Recruiting (multi‑agent)  (`consult_agent` → `_run_subagent`)
A supervisor‑style agent can recruit another specialist on a sub‑task; the sub‑agent's steps
stream nested under the parent and its conclusion is returned as the tool result.

### 5.4 Output generation  (`prepare_download` → exporters)
When the user asks to export, the agent calls `prepare_download`; the server emits an
`artifact` event (a download button). Generation is **lazy** — it runs when the user clicks, so
the just‑finished findings are always included — via the matching `@exporter`
(`report_md`, `presentation_pdf`, falling back to `presentation_tex` if `latexmk` is absent).

### 5.5 Data ingestion pipeline
Uploads route through `connectors/ingest`: CSV → SQL table (`datastore`), documents → `memory`
(RAG) after running every `@stage` in order (`normalize` → `index`). `/process` + `/process/status`
expose the queue.

### 5.6 Style governance
A central **STYLE** preamble is prepended to *every* agent and synthesis. Verbatim
(`core/orchestrator.py`):

```
OUTPUT RULES (strict, override any other style):
- BE BRIEF. Answer only what was asked, in the fewest words. Aim for a few sentences or
  one small table. Do NOT add extra sections (no 'Recommended Next Steps', 'Confidence
  Limitations', 'Summary', etc.) unless explicitly asked.
- No emojis. No filler, hype, flattery, or restating the question.
- Reference each claim with the table.column, document, or exact value used.
- If something is unknown, missing, or a tool is not implemented, say so in one line.
- If the user asks to download/export/save/get a PDF / slide deck / report, CALL the
  prepare_download tool (format 'presentation_pdf' for slides/PDF, 'report_md' for a
  report). You CAN produce downloadable files - never say you cannot.
```

### 5.7 The actual orchestration prompts (verbatim)

Every LLM call goes through `model.complete(messages, functions, system)`. The orchestrator
issues these distinct calls in a team run (each `system` is wrapped with the STYLE block above):

**(a) Per‑agent system prompt** = STYLE + the agent's own persona. Real personas:
```
# data_analyst
You are a data analyst for semiconductor yield. Quantify which process parameters drive
defects: rank parameters by correlation with the defect target and run focused SQL queries
on the defect tables. Report numbers and cite the table/columns you used. Be concise.

# equipment_specialist
You are an equipment / FDC specialist. Answer the question that was actually asked using the
data and tools available. The FDC/wafer-map tools need a lot ID or wafer ID; if that
identifier is not present in the available data, do NOT ask the user for it - report it as a
DATA GAP in your findings ... (several of these tools are stubs for now - report clearly
what is and isn't available.)
```

**(b) Routing** — pick the minimal relevant specialists (`_route_agents`).
`system:` *"You route a question to the minimal set of relevant specialists."* `user:`
```
Question: {task}

Available specialists:
- data_analyst: Correlates process parameters against the defect/yield target ...
- equipment_specialist: Pulls FDC process traces, wafer defect maps ...
- manuals_expert: Finds known failure modes from uploaded manuals / FMEA ...
- ...

List ONLY the specialist names actually needed to answer THIS question, comma-separated.
Omit irrelevant ones. If genuinely unsure, include it.
```

**(c) Clarify gate** — decide whether to ask the user ONE question (`_needs_clarification`).
`system:` *"You decide whether to ask the user one clarifying question."* `user:`
```
User question: {task}

Specialist findings:
{name}: {first 500 chars of each agent's findings}
...

Decide whether to ask the user ONE clarifying question before answering. Ask if the question
hinges on an ambiguous reference the specialists had to GUESS the meaning of - e.g. a bare
value/identifier like '844' that could be a wafer id, lot id, or something else - or if
specialists interpreted it differently. Do NOT ask merely because data is missing or a tool
is a stub. If you should ask, reply with exactly one line: CLARIFY: <one short question>.
Otherwise reply exactly: OK
```

**(d) Synthesis** — one brief conclusion across the specialists (`_synthesize`).
`system:` *"You are the lead RCA investigator. Be brief."* `user:`
```
Question: {task}

Specialist findings:
{name}: {full findings}
...

Answer the question in at most 5 sentences or one small table. Give the single most likely
cause only if relevant. Cite the table.column or document behind each point. Do NOT repeat
the specialists' full text and do NOT add extra sections.
```

**(e) Follow‑up suggestions** — data‑aware next questions (`suggest_questions`).
`system:` *"You suggest concise, useful next questions. Output only the questions."* `user:`
```
Loaded tables: {tables}. Documents: {docs}.
Question: {user_msg}
Conclusion: {first 400 chars of synthesis}

Suggest 3 short, specific questions a yield-analysis engineer might ask next given this data.
Each under 9 words, concrete. One per line, no numbering, no quotes.
```

### 5.8 Worked example — one team investigation, end to end

User selects **team mode** with 8 specialists and submits:
> *"Which process step correlates most with yield loss?"*

The client opens `POST /run` (SSE). The orchestrator (`run_team`) produces this **event stream**
(each step also persisted to the audit trail):

```
1. user_message     {text: "Which process step correlates most with yield loss?"}

   ── LLM call (b) ROUTING ──────────────────────────────────────────────
   system: STYLE + "You route a question to the minimal set of relevant specialists."
   user:   "Question: Which process step correlates most with yield loss?
            Available specialists: - data_analyst: ... - equipment_specialist: ... - manuals_expert: ..."
   → returns: "data_analyst, equipment_specialist"

2. agent_switch     {role:"dispatch", agents:["data_analyst","equipment_specialist"],
                     skipped:["manuals_expert","rca_assistant", ...]}

   ── two agents now run IN PARALLEL on threads; their events interleave (depth=1) ──

3. agent_switch     {agent:"data_analyst", role:"working", depth:1}
4. progress         {agent_scope:"data_analyst", message:"reasoning (step 1)"}

      ── LLM call (a) data_analyst's turn ──────────────────────────────
      system: STYLE + data_analyst persona
      messages: [user: "Which process step correlates most with yield loss?"]
      tools: [correlate_params_vs_yield, query_data, list_data_sources,
              + injected built-ins: load_uploaded_csv, prepare_download]
      → model returns a tool_call

5. tool_call        {agent_scope:"data_analyst", name:"correlate_params_vs_yield",
                     args:{target:"defect", ...}}
6. tool_result      {agent_scope:"data_analyst",
                     result:"etch_time r=0.71; deposition_temp r=0.38; ... (wafer_defects)"}
7. progress         {agent_scope:"data_analyst", message:"reasoning (step 2)"}
8. final            {agent_scope:"data_analyst", depth:1,
                     message:"Etch time correlates most with yield loss (r=0.71 vs the
                              defect target, wafer_defects.etch_time)..."}

   ── meanwhile, interleaved ──
3'. agent_switch    {agent:"equipment_specialist", role:"working", depth:1}
5'. tool_call       {agent_scope:"equipment_specialist", name:"query_fdc_timeseries", ...}
6'. tool_result     {agent_scope:"equipment_specialist",
                     result:"DATA GAP: query_fdc_timeseries needs a lot_id; none present in
                              wafer_defects. (tool is a stub)"}
8'. final           {agent_scope:"equipment_specialist",
                     message:"Cannot confirm at the tool level - DATA GAP: no lot_id column..."}

   ── all agents done ──

   ── LLM call (c) CLARIFY GATE ────────────────────────────────────────
   user: "User question: ... Specialist findings: data_analyst: ...  equipment_specialist: ..."
   → returns: "OK"   (no ambiguous identifier → skip; if it returned "CLARIFY: ..." the run
                      would emit needs_human and pause here)

   ── LLM call (d) SYNTHESIS ───────────────────────────────────────────
   system: STYLE + "You are the lead RCA investigator. Be brief."
   user:   "Question: ...  Specialist findings: data_analyst: <full>  equipment_specialist: <full>
            Answer in at most 5 sentences ... cite the table.column behind each point ..."
   → returns the conclusion

9. final            {synthesis:true,
                     message:"Etch time is the strongest driver of yield loss
                              (r=0.71 vs the defect target, wafer_defects.etch_time),
                              ahead of deposition temperature (r=0.38). FDC-level
                              confirmation is unavailable: no lot_id is present to join
                              equipment traces (data gap)."}

   ── LLM call (e) SUGGESTIONS ─────────────────────────────────────────
10. suggestions     {questions:["Etch time vs defect type breakdown?",
                                 "Which tool runs the etch step?",
                                 "Defect rate by wafer zone?"]}
```

**Single‑agent + human‑in‑the‑loop variant:** in single‑agent mode (`start_or_resume`) there is
no routing/synthesis — one agent's `_drive` loop streams `tool_call`/`tool_result` until `final`.
If the agent calls `ask_human`, the stream emits `needs_human` and **suspends**; the session
(keyed by `chat_id`) holds a `pending` tool‑call. The user's next `POST /run` message becomes
that tool's result and `_drive` **resumes from the same step** — that is the resumable HITL loop.

---

## 6. API surface (FastAPI, OpenAPI at `/docs`)

**Platform** — `GET /capabilities` · `GET /health` · `GET /event-schema`
**Data** — `POST /upload` · `POST /connect-db` · `GET /sources` ·
`GET /sources/{source}/{table}/preview` · `GET /documents` · `GET /documents/{source}/preview` ·
`POST /uploads/presign` · `POST /ingest-s3` · `POST /process` · `GET /process/status`
**Investigations** — `POST /run` *(SSE stream — team or single agent; pass `chat_id` for a
resumable session)* · `GET /runs` · `GET /runs/{chat_id}` *(audit trail)* ·
`GET /sessions` · `GET /sessions/{chat_id}` · `POST /sessions/{chat_id}/context` ·
`POST /agents` *(create from persona)* · `GET /suggest`
**Output** — `GET /export/formats` · `POST /export` · `GET /export`

**Streamed event types** (`/run`): `user_message`, `agent_switch`, `progress`, `thinking`,
`tool_call`, `tool_result`, `needs_human`, `context_added`, `artifact`, `final`, `error`,
`suggestions`.

---

## 7. Frontend

- **Two views** behind URL state: **Overview** (dashboard — data sources, indexed docs, tool
  count, recent investigations, agent picker) and **Investigate** (the 3‑column workspace:
  *Setup* = agents/data/tools · *Center* = conversation · *Right* = live Orchestrator trace).
- **SSE consumption:** `runChat` parses newline‑delimited JSON events and updates the
  conversation, the live status line, and a **per‑turn trace** (old turns never wiped; each step
  is click‑to‑expand).
- **5‑state UI** everywhere (empty / loading / data / error / needs‑input); data‑aware **starter
  questions** on the empty chat and **follow‑up chips** after each answer.
- **Light/dark toggle** (persisted to `localStorage`, applied via `data-theme` on `<html>`);
  **EN/DE** i18n; everything keyed off URL params (deep‑linkable).
- **Read endpoints are URL‑driven and tolerant** (validate/clamp/default — never blank‑screen
  on a junk param); mutations stay strict.

---

## 8. Setup

**Local dev (no Docker)** — backend on :8000, Vite on :5173 proxying `/api` → :8000:
```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt && python -m scripts.seed   # load sample dataset
uvicorn main:app --reload --port 8000                        # backend
cd frontend && npm install && npm run dev                    # frontend
```

**Docker:**
```bash
docker compose up -d --build
docker compose exec backend python -m scripts.seed
# frontend http://localhost:8095   ·   API http://localhost:8001/docs
```
(Compose maps host **8001→8000** (backend) and **8095→80** (frontend); change to `80:80` on a server.)

**Configuration** — `.env` (gitignored): `MOCK_LLM` (1 = offline, the default), `MODEL_ID`,
`AWS_REGION`, AWS creds, `S3_BUCKET`, optional `DATABASE_URL`, `MAX_STEPS`, `APP_TITLE`,
`DB_PATH`. With `MOCK_LLM=1` it runs fully offline.

**Extend it** — drop a decorated file in the relevant folder (any subfolder), restart, and it
appears in `/capabilities`, the orchestrator routes to it, and the UI shows it. (`docs/ADD_AN_AGENT.md`.)

---

## 9. Infrastructure / deployment

- **Terraform** (`infra/`) provisions a single **EC2** host, ships the repo (including `.env`),
  and runs the **docker compose** stack; frontend served on **port 80**.
- `terraform apply` → prints `app_url` (`http://<public-ip>`); re‑apply to redeploy; `destroy`
  to stop billing. AWS creds are read from the environment, not stored in `.tf`.

---

## 10. Notable strengths (for evaluation)

- **Parallel‑safe extensibility** — the self‑declaring/auto‑discovery model genuinely removes
  shared‑file merge conflicts; tools carry `version`/`owner` for a trustworthy growing registry.
- **Glass‑box, auditable** — every step streamed *and* persisted; claims required to cite evidence.
- **Real human‑in‑the‑loop** with resumable sessions (the Bedrock alternating‑role coalescing
  is a non‑trivial detail done correctly).
- **Routing over blind fan‑out**, plus an LLM‑decided clarification gate.
- **Symmetric outputs** — exporters are first‑class plugins like tools; lazy generation captures
  final findings.
- **Runs fully offline** (mock LLM) — easy to demo/test without cloud.

## 11. Known limitations / honest notes (for evaluation)

- **Sessions are in‑memory** (`SESSIONS`, `TEAM_SESSIONS`, `CLARIFY_PENDING` dicts) — lost on
  restart; the audit trail (`runs`) persists but live sessions don't. Needs Redis/SQL for prod.
- **Mock LLM is a skeleton**, not reasoning — offline mode demonstrates wiring, not answers.
- **Some RCA tools are stubs** (`tools/rca/stubs.py`) — flagged honestly in output by the style rules.
- **No authentication / authorization**; CORS is broad; secrets travel in `.env` (incl. shipped to EC2).
- **Single EC2, ephemeral public IP, SQLite default** — demo‑grade infra, not HA.
- **`MAX_STEPS=8`** caps agent depth; long investigations can hit the ceiling.
- Default `MODEL_ID` is `amazon.nova-micro-v1:0` (small/cheap); quality depends on the model chosen.

---

## 12. Suggested prompts to ask a reviewer

- "Evaluate the auto‑discovery/registry architecture in `core/` — is it sound, what are the
  failure modes, how would it scale to 100 tools?"
- "Review the orchestrator (`core/orchestrator.py`): the parallel team threading, the
  clarification gate, and the human‑in‑the‑loop resume logic — correctness and race conditions?"
- "Assess production‑readiness: state persistence, auth, secrets handling, infra."
- "Review the Bedrock message conversion in `core/model.py` for resumable multi‑turn tool use."
- "Critique the frontend SSE handling and the 5‑state/URL‑as‑state UX."
```
