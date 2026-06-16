import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TraceLanes } from "./Trace.jsx";
import Modal from "./Modal.jsx";
import AddAgentModal from "./AddAgentModal.jsx";
import ToolTip from "./ToolTip.jsx";
import FriendlyResult from "./FriendlyResult.jsx";
import { useI18n } from "../i18n.jsx";
import { prettyName } from "../format.js";
import { runChat, addContext, getRun, getSources, uploadFiles, connectDb, previewTable, getDocuments, previewDocument, getSuggestions, getExportFormats, exportReport, deleteSource, deleteDocument, forgetSource } from "../api.js";

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
  const { t, lang } = useI18n();
  // Pick the text for the current language from a {en, de} pair. Translation is a
  // background ADD-ON: if the requested language isn't filled yet, fall back to
  // whatever language IS available (the run language) - NEVER blank. So the UI
  // always shows readable text and silently upgrades when the translation lands.
  const pick = (i18nMap, fallback) => {
    if (i18nMap) {
      const v = i18nMap[lang] || i18nMap.en || i18nMap.de
        || Object.values(i18nMap).find((x) => (x || "").trim());
      if ((v || "").trim()) return v;
    }
    return fallback || "";
  };
  const specialists = (caps.agents || []).filter((a) => !(a.tools || []).includes("consult_agent"));
  // Resolve each tool/skill's description + limits to the CURRENT language from the
  // {en, de} pairs the backend ships (description_i18n / limits_i18n). No refetch -
  // a language toggle re-renders these from the already-loaded pairs, same as chat.
  const allTools = [...(caps.tools || []), ...(caps.skills || [])].map((x) => ({
    ...x,
    description: pick(x.description_i18n, x.description),
    limits: pick(x.limits_i18n, x.limits),
  }));
  // name -> {description, limits} so any place that only has a tool NAME (e.g. an
  // agent's tool list) can still show the full can/cannot tooltip.
  const toolInfo = Object.fromEntries(allTools.map((x) => [x.name, x]));

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
  const [openRefs, setOpenRefs] = useState(null);      // {references[], focus} for the evidence modal
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
    // Only the empty-state starter chips are (re)fetched on language change.
    // Follow-up suggestions after a turn already carry a {en, de} map and switch
    // locally, so we don't refetch and clobber them.
    if (messages.length) return;
    setSuggLoading(true);
    getSuggestions(lang).then((s) => setSuggestions(s.questions || [])).catch(() => {}).finally(() => setSuggLoading(false));
  }, [lang]); // eslint-disable-line
  useEffect(() => { getExportFormats().then((r) => setExportFormats(r.formats || [])).catch(() => {}); }, []);
  function askSuggestion(q) {
    if (busy) return;
    if (!agents.length) { setError("Select at least one agent in Setup."); return; }
    run(q);
  }

  // ---- Output generation (Download). A separate request from the chat: the user
  // can Stop it or Retry it and the conversation is never affected. ----
  async function doExport(fmt, langOverride) {
    const useLang = langOverride || lang;
    setExportOpen(false);
    if (!messages.length) { setExporting({ status: "error", error: t("nothingToExport") }); return; }
    const ac = new AbortController(); exportAbort.current = ac;
    const tag = useLang.toUpperCase();
    setExporting({ format: fmt.name, label: `${fmt.label} (${tag})`, status: "preparing", lang: useLang });
    try {
      const { filename } = await exportReport(chatId, fmt.name, ac.signal, undefined, useLang);
      setExporting({ format: fmt.name, label: `${fmt.label} (${tag})`, status: "done", filename });
      setTimeout(() => setExporting((e) => (e && e.status === "done" ? null : e)), 6000);
    } catch (e) {
      if (ac.signal.aborted) { setExporting(null); return; }
      setExporting({ format: fmt.name, label: `${fmt.label} (${tag})`, status: "error", error: String(e.message || e), lang: useLang });
    } finally {
      exportAbort.current = null;
    }
  }
  const stopExport = () => exportAbort.current && exportAbort.current.abort();
  const retryExport = () => {
    const f = exportFormats.find((x) => x.name === exporting?.format);
    if (f) doExport(f, exporting?.lang);
  };

  // The persisted audit trail is the SOURCE OF TRUTH for the trace. We split its
  // events into turns (on user_message) and never wipe earlier turns.
  function buildTurns(steps) {
    const ts = []; let cur = null;
    for (const s of steps) {
      if (s.type === "user_message") { cur = { question: s.data.text, questionI18n: s.data.text_i18n, events: [] }; ts.push(cur); }
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
        if (s.type === "user_message") msgs.push({ role: "user", text: s.data.text, i18n: s.data.text_i18n });
        else if (s.type === "final" && !s.data.depth) msgs.push({ role: "assistant", text: s.data.message, i18n: s.data.message_i18n, references: s.data.references || [] });
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
  // undefined ONLY when nothing has been deselected (= use everything). Once the user
  // has touched the selection, we send the explicit list — including an EMPTY list when
  // everything is deselected, so the backend scopes the run to NO data (not "all").
  function scopedSources() {
    if (srcOn === null && docsOn === null) return undefined;
    const s = (srcOn === null ? sources.map((x) => x.name) : srcOn);
    const d = (docsOn === null ? docs.map((x) => x.source) : docsOn);
    return [...s, ...d];   // may be [] = deselected everything = no data in scope
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
    // Show one queued row per file inside the sources box.
    setUploads(files.map((f) => ({ name: f.name, status: "queued", detail: "queued…" })));
    try {
      // Uploads run one at a time (S3-first, direct-POST fallback). The first file
      // shows 'processing'; as each finishes we refresh the source list so its real
      // row appears and its upload row drops away - one box, loads then settles.
      const r = await uploadFiles(files, (name, status) => {
        if (status === "processing") {
          setUploads((us) => us.map((u) => u.name === name
            ? { ...u, status: "processing", detail: "uploading & processing…" } : u));
        } else if (status === "done") {
          loadSources();
        }
      });
      const byName = {}; (r.results || []).forEach((x) => { byName[x.name] = x; });
      // Keep ONLY the failures visible (as error rows); successes already show as
      // real source rows below, so drop their upload rows.
      const failed = files
        .map((f) => ({ name: f.name, ...describeResult(byName[f.name]) }))
        .filter((x) => x.status === "error");
      setUploads(failed);
      await loadSources();
    } catch (err) {
      setUploads(files.map((f) => ({ name: f.name, status: "error", detail: String(err) })));
    }
    e.target.value = "";
  }
  // Remove a data source: the bundled "local" store holds uploaded tables (drop
  // the table); any other source is a connected external DB (forget the whole URL
  // connection). Both confirmed first.
  async function removeSource(s) {
    if (s.name === "local") {
      const table = (s.tables || [])[0] || s.name;
      if (!window.confirm(`Delete uploaded table "${table}"?`)) return;
      await deleteSource(s.name, table).catch(() => {});
    } else {
      if (!window.confirm(`Forget connected database "${s.name}"? The URL connection is removed.`)) return;
      await forgetSource(s.name).catch(() => {});
    }
    await loadSources();
  }
  async function removeDoc(d) {
    if (!window.confirm(`Delete document "${d.source}"?`)) return;
    await deleteDocument(d.source).catch(() => {});
    await loadSources();
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
    const tbl = s.focusTable || (s.tables || [])[0];
    if (tbl) loadPreview(s.name, tbl); else setPreview(null);
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

    // answer/paused hold the {en, de} pair when the backend supplied one, so a
    // later language toggle re-renders them from storage with no re-run.
    let answer = null, answerI18n = null, paused = null, pausedI18n = null, errored = null, references = [], answerShown = false;
    try {
      await runChat(
        { agent: "team", message, chat_id: chatId, agents,
          allow_tools: tools === null ? undefined : tools,
          sources: scopedSources(), lang },
        (ev) => {
          if (ev.type !== "user_message") appendEvent(ev);
          const d = ev.data || {}; const who = d.agent_scope ? prettyName(d.agent_scope) + ": " : "";
          // Backfill the just-shown user bubble + turn with their {en,de} pair so
          // the typed question also flips on a language switch.
          if (ev.type === "user_message" && d.text_i18n) {
            setMessages((m) => { const c = m.slice(); for (let i = c.length - 1; i >= 0; i--) { if (c[i].role === "user" && !c[i].i18n) { c[i] = { ...c[i], i18n: d.text_i18n }; break; } } return c; });
            setTurns((tt) => { if (!tt.length) return tt; const c = tt.slice(); const last = c[c.length - 1]; c[c.length - 1] = { ...last, questionI18n: d.text_i18n }; return c; });
          }
          if (ev.type === "agent_switch" && d.role === "dispatch") setStatus("dispatched to " + (d.agents || []).map(prettyName).join(", "));
          else if (ev.type === "agent_switch" && d.role === "working") setStatus(prettyName(d.agent) + " started");
          else if (ev.type === "progress") setStatus(who + d.message);
          else if (ev.type === "thinking") setStatus(who + "reasoning...");
          else if (ev.type === "tool_call") setStatus(who + "using " + prettyName(d.name));
          else if (ev.type === "tool_result") setStatus(who + prettyName(d.name) + " done");
          if (ev.type === "final" && !d.depth) {
            // Render the answer IMMEDIATELY (do not wait for the stream to close — the
            // stream stays open while background translations stream in as
            // translation_update events). Mark it answered so post-loop doesn't double-add.
            answer = d.message; answerI18n = d.message_i18n; references = d.references || []; answerShown = true;
            setMessages((m) => [...m, { role: "assistant", text: d.message, i18n: d.message_i18n, references: d.references || [], eid: d.eid }]);
            // The answer is on screen — stop showing the "working…" status line. The
            // stream stays open for SILENT background translation; the user is not told.
            setBusy(false); setStatus("");
          }
          // Background translation arrived for an already-shown event: patch its
          // other-language side in place. `questions` (a list) targets the
          // suggestions chips; everything else targets a message's {en,de} pair.
          if (ev.type === "translation_update") {
            if (d.field === "questions" && Array.isArray(d.text)) {
              setSuggestions((s) => (s && !Array.isArray(s))
                ? { ...s, [d.lang]: d.text } : s);
            } else {
              setMessages((m) => m.map((x) => x.eid && x.eid === d.eid && x.i18n
                ? { ...x, i18n: { ...x.i18n, [d.lang]: d.text } } : x));
            }
          }
          if (ev.type === "needs_human") { paused = d.question; pausedI18n = d.question_i18n; }
          if (ev.type === "error" && !d.agent_scope) errored = d.message;
          if (ev.type === "suggestions") { setSuggestions(d.questions_i18n || d.questions || []); setSuggLoading(false); }
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
    if (paused) { setMessages((m) => [...m, { role: "assistant", text: paused, i18n: pausedI18n, pending: true }]); setAwaiting(pausedI18n || paused); }
    else if (answer) { /* already rendered live on the `final` event; nothing to add here */ }
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

  // Suggestions may arrive as a flat array (starters / older events) OR as a
  // {en, de} map (live follow-ups). Resolve to the current language PER ITEM with
  // fallback: the other-language side may still be empty (background translation
  // not landed yet), so each chip falls back to whatever language it has - never
  // a blank chip. This is what keeps "Try asking" from breaking on a switch.
  const langSuggestions = (() => {
    if (Array.isArray(suggestions)) return suggestions;
    const cur = suggestions[lang] || [], en = suggestions.en || [], de = suggestions.de || [];
    const len = Math.max(cur.length, en.length, de.length);
    const out = [];
    for (let i = 0; i < len; i++) {
      const q = (cur[i] || "").trim() || (en[i] || "").trim() || (de[i] || "").trim();
      if (q) out.push(q);
    }
    return out;
  })();
  // Don't suggest a question the user already asked this chat (exact or near-dup).
  const askedNorm = messages.filter((m) => m.role === "user").map((m) => norm(pick(m.i18n, m.text)));
  const freshSuggestions = langSuggestions.filter((q) => {
    const nq = norm(q);
    return !askedNorm.some((a) => a === nq || jaccard(a, nq) > 0.6);
  });
  // The orchestrator panel only earns its space once there's something to show.
  const hasTrace = busy || turns.length > 0;

  return (
    <div className="card chat-wrap">
      <div className="chat-head">
        <button className={"panel-toggle" + (setupOpen ? " on" : "")} aria-pressed={setupOpen}
          onClick={() => setSetupOpen((v) => !v)}>
          <span className="pt-icon">{setupOpen ? "◧" : "▣"}</span>
          {setupOpen ? t("hideSetup") : t("setup")}
        </button>
        <span className="muted" title={"chat " + chatId}>{t("investigate")} · {agents.length} {t("agents")}</span>
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
                  <div key={f.name} className={"dl-row" + (f.available ? "" : " off")} title={f.description}>
                    <span className="dl-label">{f.label}</span>
                    {f.available ? (
                      <span className="dl-langs">
                        <button className={"dl-lang" + (lang === "en" ? " cur" : "")}
                          onClick={() => doExport(f, "en")}>EN</button>
                        <button className={"dl-lang" + (lang === "de" ? " cur" : "")}
                          onClick={() => doExport(f, "de")}>DE</button>
                      </span>
                    ) : (
                      <span className="muted small">{t("needs")} {(f.needs || []).join(", ")}</span>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        {hasTrace && (
          <button className={"panel-toggle" + (traceOpen ? " on" : "")} aria-pressed={traceOpen}
            onClick={() => setTraceOpen((v) => !v)}>
            <span className="pt-icon">{traceOpen ? "◨" : "▤"}</span>
            {traceOpen ? t("hideTrace") : t("trace")}
          </button>
        )}
      </div>

      <div className={"investigate-grid" + (setupOpen ? "" : " no-setup") + (traceOpen && hasTrace ? "" : " no-trace")}>

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
                  <button className="srclink" onClick={() => setInspectAgent(a)} title="what is this agent?">{prettyName(a.name)}</button>
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
                <label className="filebtn">{t("uploadFile")}<input type="file" multiple accept=".csv,.json,.pdf,.txt,.md" onChange={addFiles} /></label>
                <div className="db-mini">
                  <input placeholder="postgresql://..." value={dbUrl} onChange={(e) => setDbUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addDb()} />
                  <button onClick={addDb}>DB</button>
                </div>
              </div>
            )}
            <div className="setup-list">
              {/* In-progress / errored uploads live INSIDE the same box as the
                  sources, at the top, so mass upload reuses ONE list (loading rows
                  that settle into normal source rows) instead of a second floating
                  block that overlaps. A 'done' upload is dropped here because the
                  real source row appears below via loadSources(). */}
              {uploads.filter((u) => u.status !== "done").map((u, i) => (
                <div key={"up:" + i} className={"srcrow uprow " + u.status}>
                  {u.status === "error"
                    ? <span className="upx" aria-hidden>!</span>
                    : <span className="spin" />}
                  <span className="srclink upname" title={u.name}>{u.name}</span>
                  <span className="updetail" title={u.detail}>{u.detail}</span>
                  {u.status === "error" && (
                    <button className="srcdel" title="dismiss"
                      onClick={() => setUploads((us) => us.filter((x) => x.name !== u.name))}>×</button>
                  )}
                </div>
              ))}
              {uploads.length === 0
                && sources.filter((s) => s.name !== "local" || (s.tables || []).length).length === 0
                && docs.length === 0 && <div className="muted small">none</div>}
              {sources.map((s) => (
                s.name === "local"
                  // The 'local' store is INTERNAL - never show it as a source. Show
                  // each uploaded table it holds as its own row instead.
                  ? (s.tables || []).map((tb) => (
                      <div key={"local:" + tb} className="srcrow">
                        <input type="checkbox" checked={sourceOn(s.name)} onChange={() => toggleSource(s.name)} />
                        <button className="srclink" onClick={() => openInspect({ ...s, focusTable: tb })} title="inspect this table">
                          <span className="docicon">tbl</span> {tb}
                        </button>
                        <button className="srcdel" title="delete this table"
                          onClick={() => removeSource({ name: "local", tables: [tb] })}>×</button>
                      </div>
                    ))
                  // A connected external database: one row, forgettable.
                  : (
                    <div key={s.name} className="srcrow">
                      <input type="checkbox" checked={sourceOn(s.name)} onChange={() => toggleSource(s.name)} />
                      <button className="srclink" onClick={() => openInspect(s)} title="inspect this database">
                        <span className="docicon">db</span> {s.name} <span className="muted small">{(s.tables || []).length}t</span>
                      </button>
                      <button className="srcdel" title="forget this database connection"
                        onClick={() => removeSource(s)}>×</button>
                    </div>
                  )
              ))}
              {docs.map((d) => (
                <div key={d.source} className="srcrow">
                  <input type="checkbox" checked={docOn(d.source)} onChange={() => toggleDoc(d.source)} />
                  <button className="srclink" onClick={() => openDoc(d)} title="view this document">
                    <span className="docicon">doc</span> {d.source} <span className="muted small">{d.chars}c</span>
                  </button>
                  <button className="srcdel" title="delete this document"
                    onClick={() => removeDoc(d)}>×</button>
                </div>
              ))}
            </div>
          </div>

          <div className="setup-sec">
            <div className="setup-title">{t("toolsSkills")} <span className="muted small">{tools === null ? allTools.length : tools.length}/{allTools.length}</span></div>
            <div className="setup-list">
              {allTools.map((t) => (
                <label key={t.name} className="check">
                  <input type="checkbox" checked={toolOn(t.name)} onChange={() => toggleTool(t.name)} />
                  <ToolTip name={t.name} cap={t.description} cannot={t.limits} side="right">
                    <span className="toolname">{prettyName(t.name)}</span>
                  </ToolTip>
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
                  <div className="starter-zone">
                    <div className="starter-label">{t("tryAsking")}</div>
                    <div className="starter-grid">
                      {suggLoading
                        ? <span className="spin" title={t("loading")} />
                        : freshSuggestions.map((q, i) => (
                            <button key={i} className="starter-chip" onClick={() => askSuggestion(q)} title={q}>
                              <span className="starter-chip-kicker">Ask AI</span>
                              <span>{q}</span>
                            </button>
                          ))}
                    </div>
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
                    {m.role === "assistant" ? <Md>{pick(m.i18n, m.text)}</Md> : pick(m.i18n, m.text)}
                    {m.role === "assistant" && (m.references || []).length > 0 && (
                      <div className="refs">
                        <span className="muted small refs-label">{t("sources") || "Sources"}:</span>
                        {m.references.map((r) => (
                          <button key={r.n} className="ref-chip"
                            title={`${prettyName(r.tool)}${r.sources ? " · " + r.sources : ""} — click to verify`}
                            onClick={() => setOpenRefs({ references: m.references, focus: r.n })}>
                            [{r.n}] {r.sources || prettyName(r.tool)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
            ))}
            {busy && <div className="statusline"><span className="spin" /> {status || "working..."}</div>}
          </div>
          {messages.length > 0 && !busy && !awaiting && (suggLoading || freshSuggestions.length > 0) && (
            <div className="suggestions followup-zone">
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

        {traceOpen && hasTrace && (
        <aside className="feed" ref={feedRef} onScroll={() => onScroll(feedRef, stickFeed)}>
          <div className="feed-title">{t("orchestrator")} <span className="muted small">- {t("clickStep")}</span></div>
          {turns.length === 0 && <div className="feed-empty muted small">{t("stepsAppear")}</div>}
          {turns.map((turn, i) => (
            <div key={i} className="turn-block">
              {turn.question && <div className="turn-q" title={pick(turn.questionI18n, turn.question)}>{pick(turn.questionI18n, turn.question)}</div>}
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

      {openRefs && (() => {
        // A chip click focuses ONE reference -> show only that one. The "View all
        // sources" link clears the focus to reveal the full list.
        const showOne = openRefs.focus != null;
        const shown = showOne
          ? openRefs.references.filter((r) => r.n === openRefs.focus)
          : openRefs.references;
        const title = showOne
          ? `${t("evidenceOne") || "Source"} [${openRefs.focus}]`
          : (t("evidenceTitle") || "Where this answer comes from");
        return (
        <Modal title={title} wide onClose={() => setOpenRefs(null)}>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("evidenceIntro") || "Each item is the exact tool the system ran and the real result it returned from your data — so every claim is verifiable and reproducible."}
          </p>
          {shown.map((r) => (
            <div key={r.n} className="ref-item">
              <div className="ref-item-head">
                <span className="ref-num">[{r.n}]</span>
                <span className="ref-from">
                  {(t("fromData") || "From")} <strong>{r.sources || prettyName(r.tool)}</strong>
                  <span className="muted small"> · {prettyName(r.agent)} ran <code>{r.tool}</code></span>
                </span>
              </div>
              <div className="ref-repro">
                <span className="muted small">{t("howToReproduce") || "Reproduce"}:</span>{" "}
                <code>{r.call}</code>
              </div>
              <FriendlyResult result={r.result} />
            </div>
          ))}
          {showOne && openRefs.references.length > 1 && (
            <button type="button" className="fr-toggle"
              onClick={() => setOpenRefs({ ...openRefs, focus: null })}>
              {t("viewAllSources") || "View all sources"} ({openRefs.references.length})
            </button>
          )}
        </Modal>
        );
      })()}

      {inspectAgent && (
        <Modal title={`Agent: ${prettyName(inspectAgent.name)}`} onClose={() => setInspectAgent(null)}>
          <p className="muted">{pick(inspectAgent.description_i18n, inspectAgent.description)}</p>
          {(() => {
            const A = inspectAgent;
            const rows = [
              ["whenToUse", pick(A.when_to_use_i18n, A.when_to_use)],
              ["howToUse", pick(A.how_to_use_i18n, A.how_to_use)],
              ["whatToUseFor", pick(A.what_to_use_for_i18n, A.what_to_use_for)],
              ["whatNotToUseFor", pick(A.what_not_to_use_for_i18n, A.what_not_to_use_for)],
            ].filter(([, v]) => (v || "").trim());
            return rows.length > 0 && (
              <div className="agent-guide">
                {rows.map(([k, v]) => (
                  <div key={k} className={"ag-row" + (k === "whatNotToUseFor" ? " ag-not" : "")}>
                    <div className="ag-label">{t(k)}</div>
                    <div className="ag-val">{v}</div>
                  </div>
                ))}
              </div>
            );
          })()}
          <div className="setup-title" style={{ marginTop: 12 }}>{t("toolsItMayUse")} ({(inspectAgent.tools || []).length})</div>
          <div className="chips">
            {(inspectAgent.tools || []).map((t) => (
              <ToolTip key={t} name={t} cap={toolInfo[t]?.description} cannot={toolInfo[t]?.limits}>
                <span className="chip on">{t}</span>
              </ToolTip>
            ))}
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
