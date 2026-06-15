import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TraceLanes } from "./Trace.jsx";
import Modal from "./Modal.jsx";
import AddAgentModal from "./AddAgentModal.jsx";
import { useI18n } from "../i18n.jsx";
import { runChat, addContext, getRun, getSources, uploadFiles, connectDb, previewTable, getDocuments, previewDocument, getSuggestions, getExportFormats, exportReport } from "../api.js";

const Md = ({ children }) => (
  <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown></div>
);

// Suggestion de-duplication vs. what the user already asked.
const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
function jaccard(a, b) {
  const A = new Set(a.split(" ")), B = new Set(b.split(" "));
  const inter = [...A].filter((x) => B.has(x)).length;
  const uni = new Set([...A, ...B]).size;
  return uni ? inter / uni : 0;
}

// Investigation workspace: Setup (agents / data sources / tools) on the left,
// conversation in the middle, the orchestrator trace on the right. The trace is
// kept PER TURN so previous turns are never wiped on a reply. One input: while it
// works your text is ADDED CONTEXT, once it is done it is a REPLY.
export default function ChatPanel({ caps, chatId, initialAgents = [], onBack, refreshCaps }) {
  const { t } = useI18n();
  const specialists = (caps.agents || []).filter((a) => !(a.tools || []).includes("consult_agent"));
  const allTools = [...(caps.tools || []), ...(caps.skills || [])];

  const [agents, setAgents] = useState(initialAgents);
  const [tools, setTools] = useState(null);     // null = all
  const [sources, setSources] = useState([]);
  const [srcOn, setSrcOn] = useState(null);     // null = all
  const [docsOn, setDocsOn] = useState(null);   // selected documents; null = all
  const [adding, setAdding] = useState(false);
  const [dbUrl, setDbUrl] = useState("");
  const [uploads, setUploads] = useState([]);   // per-file upload feedback
  const [showAddAgent, setShowAddAgent] = useState(false);
  const [inspect, setInspect] = useState(null); // source being inspected
  const [preview, setPreview] = useState(null); // {table, columns, rows, loading, error}
  const [inspectAgent, setInspectAgent] = useState(null); // agent being inspected
  const [docs, setDocs] = useState([]);          // uploaded documents
  const [inspectDoc, setInspectDoc] = useState(null); // {source, text, loading}
  const [suggestions, setSuggestions] = useState([]); // suggested questions
  const [suggLoading, setSuggLoading] = useState(true); // initial /suggest in flight
  const [exportFormats, setExportFormats] = useState([]); // output formats
  const [exportOpen, setExportOpen] = useState(false);    // download menu open
  const [exporting, setExporting] = useState(null);       // {format,label,status,error,filename}

  const [messages, setMessages] = useState([]);
  const [turns, setTurns] = useState([]);       // [{question, events:[]}] - one per turn, never wiped
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [awaiting, setAwaiting] = useState(null);
  const [error, setError] = useState(null);
  const [lastMsg, setLastMsg] = useState("");
  const [setupOpen, setSetupOpen] = useState(true);
  const [traceOpen, setTraceOpen] = useState(true);

  const abortRef = useRef(null);
  const exportAbort = useRef(null);
  const msgRef = useRef(null), feedRef = useRef(null), taRef = useRef(null);
  const stickMsg = useRef(true), stickFeed = useRef(true);
  function autoGrow(el) { if (!el) return; el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; }

  useEffect(() => { if (!agents.length && specialists.length) setAgents(specialists.map((a) => a.name)); }, [caps]); // eslint-disable-line

  async function loadSources() {
    try {
      const s = await getSources();
      setSources(s.sources || []);
      setSrcOn((on) => on ?? (s.sources || []).map((x) => x.name));
      const d = await getDocuments();
      setDocs(d.documents || []);
    } catch { /* */ }
  }
  async function openDoc(d) {
    setInspectDoc({ source: d.source, loading: true });
    const r = await previewDocument(d.source).catch((e) => ({ text: "", error: String(e) }));
    setInspectDoc({ source: d.source, text: r.text || "", error: r.error });
  }
  useEffect(() => { loadSources(); }, []);
  useEffect(() => {
    setSuggLoading(true);
    getSuggestions().then((s) => setSuggestions(s.questions || [])).catch(() => {}).finally(() => setSuggLoading(false));
  }, []);
  useEffect(() => { getExportFormats().then((r) => setExportFormats(r.formats || [])).catch(() => {}); }, []);
  function askSuggestion(q) {
    if (busy) return;
    if (!agents.length) { setError("Select at least one agent in Setup."); return; }
    run(q);
  }

  // ---- Output generation (Download). A separate request from the chat: the user
  // can Stop it or Retry it and the conversation is never affected. ----
  async function doExport(fmt) {
    setExportOpen(false);
    if (!messages.length) { setExporting({ status: "error", error: t("nothingToExport") }); return; }
    const ac = new AbortController(); exportAbort.current = ac;
    setExporting({ format: fmt.name, label: fmt.label, status: "preparing" });
    try {
      const { filename } = await exportReport(chatId, fmt.name, ac.signal);
      setExporting({ format: fmt.name, label: fmt.label, status: "done", filename });
      setTimeout(() => setExporting((e) => (e && e.status === "done" ? null : e)), 6000);
    } catch (e) {
      if (ac.signal.aborted) { setExporting(null); return; }
      setExporting({ format: fmt.name, label: fmt.label, status: "error", error: String(e.message || e) });
    } finally {
      exportAbort.current = null;
    }
  }
  const stopExport = () => exportAbort.current && exportAbort.current.abort();
  const retryExport = () => {
    const f = exportFormats.find((x) => x.name === exporting?.format);
    if (f) doExport(f);
  };

  // The persisted audit trail is the SOURCE OF TRUTH for the trace. We split its
  // events into turns (on user_message) and never wipe earlier turns.
  function buildTurns(steps) {
    const ts = []; let cur = null;
    for (const s of steps) {
      if (s.type === "user_message") { cur = { question: s.data.text, events: [] }; ts.push(cur); }
      else { if (!cur) { cur = { question: "", events: [] }; ts.push(cur); } cur.events.push({ type: s.type, data: s.data, ts: s.ts }); }
    }
    return ts;
  }
  async function reloadFromAudit() {
    try {
      const r = await getRun(chatId);
      if (!r?.steps?.length) return;
      setTurns(buildTurns(r.steps));
      const msgs = [];
      for (const s of r.steps) {
        if (s.type === "user_message") msgs.push({ role: "user", text: s.data.text });
        else if (s.type === "final" && !s.data.depth) msgs.push({ role: "assistant", text: s.data.message });
        else if (s.type === "artifact" && !msgs.some((x) => x.role === "artifact" && x.format === s.data.format))
          msgs.push({ role: "artifact", format: s.data.format, label: s.data.label,
                      extension: s.data.extension, available: s.data.available !== false });
      }
      setMessages(msgs);
    } catch { /* */ }
  }
  async function reloadTurns() {   // refresh only the trace (keep live messages)
    try { const r = await getRun(chatId); if (r?.steps?.length) setTurns(buildTurns(r.steps)); } catch { /* */ }
  }
  // Restore a past chat on open.
  useEffect(() => { reloadFromAudit(); }, [chatId]); // eslint-disable-line

  function onScroll(ref, stick) {
    const el = ref.current; if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }
  useEffect(() => { if (stickMsg.current && msgRef.current) msgRef.current.scrollTop = msgRef.current.scrollHeight; }, [messages, status]);
  useEffect(() => { if (stickFeed.current && feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [turns]);

  const toggle = (list, set, n) => set(list.includes(n) ? list.filter((x) => x !== n) : [...list, n]);
  const toolOn = (n) => (tools === null ? true : tools.includes(n));
  function toggleTool(n) {
    const cur = tools === null ? allTools.map((t) => t.name) : tools;
    const next = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n];
    setTools(next.length === allTools.length ? null : next);
  }
  const sourceOn = (n) => (srcOn === null ? true : srcOn.includes(n));
  function toggleSource(n) {
    const cur = srcOn === null ? sources.map((s) => s.name) : srcOn;
    const next = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n];
    setSrcOn(next.length === sources.length ? null : next);
  }
  const docOn = (n) => (docsOn === null ? true : docsOn.includes(n));
  function toggleDoc(n) {
    const cur = docsOn === null ? docs.map((d) => d.source) : docsOn;
    const next = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n];
    setDocsOn(next.length === docs.length ? null : next);
  }
  // The data the run is scoped to: selected SQL sources + selected documents.
  // undefined when nothing is deselected (= use everything).
  function scopedSources() {
    if (srcOn === null && docsOn === null) return undefined;
    const s = (srcOn === null ? sources.map((x) => x.name) : srcOn);
    const d = (docsOn === null ? docs.map((x) => x.source) : docsOn);
    const list = [...s, ...d];
    return list.length ? list : undefined;
  }

  function describeResult(x) {
    if (!x) return { status: "error", detail: "no response" };
    if (x.kind === "dataset") return { status: "done", detail: `table ${x.table}, ${x.rows} rows` };
    if (x.kind === "document") return { status: "done", detail: `indexed, ${x.chars} chars` };
    if (x.kind === "error" || x.kind === "skipped") return { status: "error", detail: x.reason || x.kind };
    return { status: "done", detail: "uploaded" };
  }
  async function addFiles(e) {
    const files = Array.from(e.target.files); if (!files.length) return;
    setUploads(files.map((f) => ({ name: f.name, status: "processing", detail: "uploading and processing..." })));
    try {
      const r = await uploadFiles(files);
      const byName = {}; (r.results || []).forEach((x) => { byName[x.name] = x; });
      const results = files.map((f) => ({ name: f.name, ...describeResult(byName[f.name]) }));
      setUploads(results);
      await loadSources();
      // The file now appears in the list below; clear the transient feedback
      // (keep it only if something errored so the user can see it).
      if (results.every((x) => x.status === "done")) setTimeout(() => setUploads([]), 3500);
    } catch (err) {
      setUploads(files.map((f) => ({ name: f.name, status: "error", detail: String(err) })));
    }
    e.target.value = "";
  }
  async function addDb() {
    if (!dbUrl.trim()) return;
    setAdding(true); const r = await connectDb(dbUrl.trim()).catch(() => ({ connected: false }));
    setUploads([{ name: dbUrl.trim().slice(0, 40), status: r.connected ? "done" : "error",
      detail: r.connected ? `connected ${r.name} (${r.dialect}), ${r.tables?.length || 0} tables` : (r.error || "could not connect") }]);
    setDbUrl(""); await loadSources(); setAdding(false);
  }

  async function openInspect(s) {
    setInspect(s);
    if (s.tables?.length) loadPreview(s.name, s.tables[0]); else setPreview(null);
  }
  async function loadPreview(source, table) {
    setPreview({ table, loading: true });
    const r = await previewTable(source, table).catch((e) => ({ error: String(e) }));
    setPreview({ table, columns: r.columns || [], rows: r.rows || [], error: r.error });
  }
  async function onAgentCreated(nm) {
    setShowAddAgent(false);
    if (refreshCaps) await refreshCaps();
    setAgents((a) => (a.includes(nm) ? a : [...a, nm]));
  }

  function appendEvent(ev) {
    setTurns((t) => {
      if (!t.length) return t;
      const c = t.slice(); const last = c[c.length - 1];
      c[c.length - 1] = { ...last, events: [...last.events, ev] };
      return c;
    });
  }

  async function run(message) {
    setMessages((m) => [...m, { role: "user", text: message }]);
    setTurns((t) => [...t, { question: message, events: [] }]);   // new turn, keep old ones
    stickMsg.current = true; stickFeed.current = true;
    setBusy(true); setAwaiting(null); setError(null); setStatus("dispatching..."); setLastMsg(message);
    setSuggestions([]); setSuggLoading(true);
    const ac = new AbortController(); abortRef.current = ac;

    let answer = "", paused = null, errored = null;
    try {
      await runChat(
        { agent: "team", message, chat_id: chatId, agents,
          allow_tools: tools === null ? undefined : tools,
          sources: scopedSources() },
        (ev) => {
          if (ev.type !== "user_message") appendEvent(ev);
          const d = ev.data || {}; const who = d.agent_scope ? d.agent_scope + ": " : "";
          if (ev.type === "agent_switch" && d.role === "dispatch") setStatus("dispatched to " + (d.agents || []).join(", "));
          else if (ev.type === "agent_switch" && d.role === "working") setStatus(d.agent + " started");
          else if (ev.type === "progress") setStatus(who + d.message);
          else if (ev.type === "thinking") setStatus(who + "reasoning...");
          else if (ev.type === "tool_call") setStatus(who + "using " + d.name);
          else if (ev.type === "tool_result") setStatus(who + d.name + " done");
          if (ev.type === "final" && !d.depth) answer = d.message;
          if (ev.type === "needs_human") paused = d.question;
          if (ev.type === "error" && !d.agent_scope) errored = d.message;
          if (ev.type === "suggestions") { setSuggestions(d.questions || []); setSuggLoading(false); }
          if (ev.type === "artifact") setMessages((m) =>
            m.some((x) => x.role === "artifact" && x.format === d.format) ? m
              : [...m, { role: "artifact", format: d.format, label: d.label,
                         extension: d.extension, available: d.available !== false }]);
        }, ac.signal);
    } catch (e) {
      if (ac.signal.aborted) { setMessages((m) => [...m, { role: "note", text: "stopped" }]); setBusy(false); setStatus(""); abortRef.current = null; return; }
      errored = String(e.message || e);
    }
    abortRef.current = null; setStatus("");
    if (paused) { setMessages((m) => [...m, { role: "assistant", text: paused, pending: true }]); setAwaiting(paused); }
    else if (answer) setMessages((m) => [...m, { role: "assistant", text: answer }]);
    else if (errored) { setError(errored); setMessages((m) => [...m, { role: "assistant", text: "Error: " + errored, error: true }]); }
    else setMessages((m) => [...m, { role: "assistant", text: "_(no answer was produced)_" }]);
    setBusy(false); setSuggLoading(false);
    reloadTurns();   // reconcile the trace with the authoritative audit trail
  }

  function submit() {
    const text = input.trim(); if (!text) return; setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    if (busy) { addContext(chatId, text).catch(() => {}); setMessages((m) => [...m, { role: "note", text: "context added: " + text }]); return; }
    if (!agents.length) { setError("Select at least one agent in Setup."); return; }
    run(text);
  }
  const stop = () => abortRef.current && abortRef.current.abort();
  const retry = () => { if (lastMsg) { setError(null); run(lastMsg); } };

  // Don't suggest a question the user already asked this chat (exact or near-dup).
  const askedNorm = messages.filter((m) => m.role === "user").map((m) => norm(m.text));
  const freshSuggestions = suggestions.filter((q) => {
    const nq = norm(q);
    return !askedNorm.some((a) => a === nq || jaccard(a, nq) > 0.6);
  });

  return (
    <div className="card chat-wrap">
      <div className="chat-head">
        {onBack && <button onClick={onBack}>← {t("overview")}</button>}
        <button className="mini" onClick={() => setSetupOpen((v) => !v)}>{setupOpen ? t("hideSetup") : t("setup")}</button>
        <span className="muted">{t("investigate")} - {agents.length}<span className="chatid"> - {chatId.slice(0, 8)}</span></span>
        {busy && <button className="stopbtn" onClick={stop}>{t("stop")}</button>}
        <div className="dl-wrap">
          <button className="mini" disabled={!messages.length} title={t("downloadHint")}
            onClick={() => setExportOpen((v) => !v)}>{t("download")} ▾</button>
          {exportOpen && (
            <>
              <div className="menu-backdrop" onClick={() => setExportOpen(false)} />
              <div className="dl-menu">
                <div className="dl-head">{t("generateOutput")}</div>
                {exportFormats.length === 0 && <div className="dl-item muted small">{t("loading")}</div>}
                {exportFormats.map((f) => (
                  <button key={f.name} className="dl-item" disabled={!f.available}
                    onClick={() => doExport(f)} title={f.description}>
                    <span className="dl-label">{f.label}</span>
                    {!f.available && <span className="muted small">{t("needs")} {(f.needs || []).join(", ")}</span>}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        <button className="mini" onClick={() => setTraceOpen((v) => !v)}>{traceOpen ? t("hideTrace") : t("trace")}</button>
      </div>

      <div className={"investigate-grid" + (setupOpen ? "" : " no-setup") + (traceOpen ? "" : " no-trace")}>

        {setupOpen && (
        <aside className="setup">
          <div className="setup-sec">
            <div className="setup-title">{t("agents")} <span className="muted small">{agents.length}/{specialists.length}</span>
              <button className="mini" onClick={() => setShowAddAgent(true)}>{t("addAgent")}</button>
            </div>
            <div className="setup-list">
              {specialists.map((a) => (
                <div key={a.name} className="srcrow">
                  <input type="checkbox" checked={agents.includes(a.name)} onChange={() => toggle(agents, setAgents, a.name)} />
                  <button className="srclink" onClick={() => setInspectAgent(a)} title="what is this agent?">{a.name}</button>
                </div>
              ))}
            </div>
          </div>

          <div className="setup-sec">
            <div className="setup-title">{t("dataSources")}
              <button className="mini" onClick={() => setAdding((v) => !v)}>{adding ? t("cancel") : t("add")}</button>
            </div>
            {adding && (
              <div className="addsrc">
                <label className="filebtn">{t("uploadFile")}<input type="file" multiple accept=".csv,.pdf,.txt,.md" onChange={addFiles} /></label>
                <div className="db-mini">
                  <input placeholder="postgresql://..." value={dbUrl} onChange={(e) => setDbUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addDb()} />
                  <button onClick={addDb}>DB</button>
                </div>
              </div>
            )}
            {uploads.length > 0 && (
              <div className="uploads">
                {uploads.map((u, i) => (
                  <div key={i} className={"uprow " + u.status}>
                    {u.status === "processing" && <span className="spin" />}
                    <span className="upname" title={u.name}>{u.name}</span>
                    <span className="updetail">{u.detail}</span>
                    {u.status !== "processing" && (
                      <button className="updismiss" title="dismiss"
                        onClick={() => setUploads((us) => us.filter((_, j) => j !== i))}>x</button>
                    )}
                  </div>
                ))}
              </div>
            )}
            {sources.length === 0 && docs.length === 0 && <div className="muted small">none</div>}
            <div className="setup-list">
              {sources.map((s) => (
                <div key={s.name} className="srcrow">
                  <input type="checkbox" checked={sourceOn(s.name)} onChange={() => toggleSource(s.name)} />
                  <button className="srclink" onClick={() => openInspect(s)} title="inspect this source">
                    {s.name} <span className="muted small">{(s.tables || []).length}t</span>
                  </button>
                </div>
              ))}
              {docs.map((d) => (
                <div key={d.source} className="srcrow">
                  <input type="checkbox" checked={docOn(d.source)} onChange={() => toggleDoc(d.source)} />
                  <button className="srclink" onClick={() => openDoc(d)} title="view this document">
                    <span className="docicon">doc</span> {d.source} <span className="muted small">{d.chars}c</span>
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="setup-sec">
            <div className="setup-title">{t("toolsSkills")} <span className="muted small">{tools === null ? allTools.length : tools.length}/{allTools.length}</span></div>
            <div className="setup-list">
              {allTools.map((t) => (
                <label key={t.name} className="check" title={t.description}>
                  <input type="checkbox" checked={toolOn(t.name)} onChange={() => toggleTool(t.name)} />
                  <span>{t.name}</span>
                </label>
              ))}
            </div>
          </div>
        </aside>
        )}

        <div className="center">
          <div className={"messages" + (messages.length === 0 ? " empty" : "")} ref={msgRef} onScroll={() => onScroll(msgRef, stickMsg)}>
            {messages.length === 0 && (
              <div className="empty-hero">
                <div className="empty-mark">◎</div>
                <h2>{t("startInvestigation")}</h2>
                <p>{t("describePrompt")}</p>
                {(suggLoading || freshSuggestions.length > 0) && (
                  <div className="starter-grid">
                    {suggLoading
                      ? <span className="spin" title={t("loading")} />
                      : freshSuggestions.map((q, i) => (
                          <button key={i} className="starter-chip" onClick={() => askSuggestion(q)} title={q}>{q}</button>
                        ))}
                  </div>
                )}
              </div>
            )}
            {messages.map((m, i) => (
              m.role === "note"
                ? <div key={i} className="msgnote">{m.text}</div>
                : m.role === "artifact"
                ? <div key={i} className="artifact-card">
                    <span className="art-icon">⬇</span>
                    <div className="art-text">
                      <div className="art-label">{m.label}</div>
                      <div className="muted small">{t("readyToDownload")}</div>
                    </div>
                    <button className="primary" disabled={!m.available || exporting?.status === "preparing"}
                      onClick={() => doExport({ name: m.format, label: m.label })}>{t("download")}</button>
                  </div>
                : <div key={i} className={"msg " + m.role + (m.pending ? " pendingq" : "") + (m.error ? " errmsg" : "")}>
                    {m.pending && <span className="ask">needs your input</span>}
                    {m.role === "assistant" ? <Md>{m.text}</Md> : m.text}
                  </div>
            ))}
            {busy && <div className="statusline"><span className="spin" /> {status || "working..."}</div>}
          </div>
          {messages.length > 0 && !busy && !awaiting && (suggLoading || freshSuggestions.length > 0) && (
            <div className="suggestions">
              <span className="muted small sugg-label">{t("tryAsking")}</span>
              {suggLoading
                ? <span className="spin" title={t("loading")} />
                : freshSuggestions.map((q, i) => (
                    <button key={i} className="suggestion-chip" onClick={() => askSuggestion(q)} title={q}>{q}</button>
                  ))}
            </div>
          )}
          {exporting && (
            <div className={"exportbar " + exporting.status}>
              {exporting.status === "preparing" && (
                <><span className="spin" /> <span>{t("preparing")} {exporting.label}…</span>
                  <button onClick={stopExport}>{t("stop")}</button></>
              )}
              {exporting.status === "done" && (
                <><span className="ok">✓ {t("downloaded")} {exporting.filename}</span>
                  <button className="xbtn" title="dismiss" onClick={() => setExporting(null)}>×</button></>
              )}
              {exporting.status === "error" && (
                <><span className="warn">{exporting.error}</span>
                  {exporting.format && <button onClick={retryExport}>{t("retry")}</button>}
                  <button className="xbtn" title="dismiss" onClick={() => setExporting(null)}>×</button></>
              )}
            </div>
          )}
          {awaiting && <div className="askbanner"><strong>{t("needsInput")}</strong> {t("typeAnswer")}</div>}
          {error && <div className="retrybar">{error}<button onClick={retry}>{t("retry")}</button></div>}
          <div className="row composer">
            <textarea ref={taRef} rows={1} value={input}
              onChange={(e) => { setInput(e.target.value); autoGrow(e.target); }}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder={busy ? t("contextPlaceholder") : awaiting ? t("answerPlaceholder") : t("askPlaceholder")} />
            <button className="primary" onClick={submit}>{busy ? t("addContext") : awaiting ? t("reply") : t("investigateBtn")}</button>
          </div>
        </div>

        {traceOpen && (
        <aside className="feed" ref={feedRef} onScroll={() => onScroll(feedRef, stickFeed)}>
          <div className="feed-title">{t("orchestrator")} <span className="muted small">- {t("clickStep")}</span></div>
          {turns.length === 0 && <div className="feed-empty muted small">{t("stepsAppear")}</div>}
          {turns.map((turn, i) => (
            <div key={i} className="turn-block">
              {turn.question && <div className="turn-q" title={turn.question}>{turn.question}</div>}
              <TraceLanes events={turn.events} leadLabel="orchestrator" />
            </div>
          ))}
        </aside>
        )}
      </div>

      {showAddAgent && <AddAgentModal caps={caps} onClose={() => setShowAddAgent(false)} onCreated={onAgentCreated} />}

      {inspectDoc && (
        <Modal title={`Document: ${inspectDoc.source}`} wide onClose={() => setInspectDoc(null)}>
          {inspectDoc.loading && <div className="muted small">loading...</div>}
          {inspectDoc.error && <div className="warn small">{inspectDoc.error}</div>}
          {!inspectDoc.loading && !inspectDoc.error && (
            <pre className="doc-text">{inspectDoc.text || "(empty)"}</pre>
          )}
        </Modal>
      )}

      {inspectAgent && (
        <Modal title={`Agent: ${inspectAgent.name}`} onClose={() => setInspectAgent(null)}>
          <p className="muted">{inspectAgent.description}</p>
          <div className="setup-title" style={{ marginTop: 12 }}>Tools it may use ({(inspectAgent.tools || []).length})</div>
          <div className="chips">
            {(inspectAgent.tools || []).map((t) => <span key={t} className="chip on">{t}</span>)}
            {!(inspectAgent.tools || []).length && <span className="muted small">none</span>}
          </div>
          <div className="row end" style={{ marginTop: 14 }}>
            <button className="primary" onClick={() => { if (!agents.includes(inspectAgent.name)) setAgents((a) => [...a, inspectAgent.name]); setInspectAgent(null); }}>
              Use this agent
            </button>
          </div>
        </Modal>
      )}

      {inspect && (
        <Modal title={`Source: ${inspect.name} (${inspect.dialect})`} wide onClose={() => { setInspect(null); setPreview(null); }}>
          <div className="inspect-tabs">
            {(inspect.tables || []).map((t) => (
              <button key={t} className={"chip" + (preview?.table === t ? " on" : "")} onClick={() => loadPreview(inspect.name, t)}>{t}</button>
            ))}
            {(!inspect.tables || !inspect.tables.length) && <span className="muted small">no tables in this source</span>}
          </div>
          {preview?.loading && <div className="muted small">loading...</div>}
          {preview?.error && <div className="warn small">{preview.error}</div>}
          {preview && !preview.loading && !preview.error && (
            <div className="preview-wrap">
              <table className="preview-table">
                <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{preview.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{v === null ? "" : String(v)}</td>)}</tr>)}</tbody>
              </table>
              <div className="muted small">showing {preview.rows.length} rows (max 50)</div>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
