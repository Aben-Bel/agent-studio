import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TraceLanes } from "./Trace.jsx";
import { runChat, addContext, getRun, getSources, uploadFiles, connectDb } from "../api.js";

const Md = ({ children }) => (
  <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown></div>
);

// Investigation workspace: Setup (agents / data sources / tools) on the left,
// conversation in the middle, live orchestrator trace on the right. The page is
// fixed; each column scrolls on its own. One input: while it works your text is
// ADDED CONTEXT, once it's done it's a REPLY.
export default function ChatPanel({ caps, chatId, initialAgents = [], onBack }) {
  const specialists = (caps.agents || []).filter((a) => !(a.tools || []).includes("consult_agent"));
  const allTools = [...(caps.tools || []), ...(caps.skills || [])];

  const [agents, setAgents] = useState(initialAgents);
  const [tools, setTools] = useState(null);     // null = all
  const [sources, setSources] = useState([]);
  const [srcOn, setSrcOn] = useState(null);     // null = all
  const [adding, setAdding] = useState(false);
  const [dbUrl, setDbUrl] = useState("");

  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [awaiting, setAwaiting] = useState(null);
  const [error, setError] = useState(null);
  const [lastMsg, setLastMsg] = useState("");
  const [setupOpen, setSetupOpen] = useState(true);
  const [traceOpen, setTraceOpen] = useState(true);
  const abortRef = useRef(null);
  const msgRef = useRef(null), feedRef = useRef(null), taRef = useRef(null);
  const stickMsg = useRef(true), stickFeed = useRef(true);
  function autoGrow(el) { if (!el) return; el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; }

  // defaults once capabilities/sources load
  useEffect(() => { if (!agents.length && specialists.length) setAgents(specialists.map((a) => a.name)); }, [caps]); // eslint-disable-line
  async function loadSources() {
    try { const s = await getSources(); setSources(s.sources || []); setSrcOn((on) => on ?? (s.sources || []).map((x) => x.name)); }
    catch { /* */ }
  }
  useEffect(() => { loadSources(); }, []);

  // restore a past chat from the audit trail (works for team + single)
  useEffect(() => {
    let alive = true;
    getRun(chatId).then((r) => {
      if (!alive || !r?.steps?.length) return;
      const msgs = [];
      for (const s of r.steps) {
        if (s.type === "user_message") msgs.push({ role: "user", text: s.data.text });
        else if (s.type === "final" && !s.data.depth) msgs.push({ role: "assistant", text: s.data.message });
      }
      setMessages(msgs);
      setEvents(r.steps.map((s) => ({ type: s.type, data: s.data, ts: s.ts })));
    }).catch(() => {});
    return () => { alive = false; };
  }, [chatId]);

  function onScroll(ref, stick) {
    const el = ref.current; if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }
  useEffect(() => { if (stickMsg.current && msgRef.current) msgRef.current.scrollTop = msgRef.current.scrollHeight; }, [messages, status]);
  useEffect(() => { if (stickFeed.current && feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [events]);

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

  async function addFiles(e) {
    const files = Array.from(e.target.files); if (!files.length) return;
    setAdding(true); await uploadFiles(files).catch(() => {}); await loadSources(); setAdding(false); e.target.value = "";
  }
  async function addDb() {
    if (!dbUrl.trim()) return;
    setAdding(true); await connectDb(dbUrl.trim()).catch(() => {}); setDbUrl(""); await loadSources(); setAdding(false);
  }

  async function run(message) {
    setMessages((m) => [...m, { role: "user", text: message }]);
    setEvents([]); stickMsg.current = true; stickFeed.current = true;
    setBusy(true); setAwaiting(null); setError(null); setStatus("dispatching..."); setLastMsg(message);
    const ac = new AbortController(); abortRef.current = ac;
    let answer = "", paused = null, errored = null;
    try {
      await runChat(
        { agent: "team", message, chat_id: chatId, agents,
          allow_tools: tools === null ? undefined : tools,
          sources: srcOn === null ? undefined : srcOn },
        (ev) => {
          setEvents((e) => [...e, ev]);
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
    setBusy(false);
  }

  function submit() {
    const text = input.trim(); if (!text) return; setInput("");
    if (busy) { addContext(chatId, text).catch(() => {}); setMessages((m) => [...m, { role: "note", text: "context added: " + text }]); return; }
    if (!agents.length) { setError("Select at least one agent in Setup."); return; }
    run(text);
  }
  const stop = () => abortRef.current && abortRef.current.abort();
  const retry = () => { if (lastMsg) { setError(null); run(lastMsg); } };

  return (
    <div className="card chat-wrap">
      <div className="chat-head">
        {onBack && <button onClick={onBack}>Overview</button>}
        <button className="mini" onClick={() => setSetupOpen((v) => !v)}>{setupOpen ? "Hide setup" : "Setup"}</button>
        <span className="muted">Investigation - {agents.length} agent{agents.length === 1 ? "" : "s"}<span className="chatid"> - {chatId.slice(0, 8)}</span></span>
        {busy && <button className="stopbtn" onClick={stop}>Stop</button>}
        <button className="mini" onClick={() => setTraceOpen((v) => !v)}>{traceOpen ? "Hide trace" : "Trace"}</button>
      </div>

      <div className="investigate-grid"
        style={{ gridTemplateColumns: `${setupOpen ? "210px " : ""}minmax(0,1fr)${traceOpen ? " 340px" : ""}` }}>
        {/* ---- Setup column ---- */}
        {setupOpen && (
        <aside className="setup">
          <div className="setup-sec">
            <div className="setup-title">Agents <span className="muted small">{agents.length}/{specialists.length}</span></div>
            {specialists.map((a) => (
              <label key={a.name} className="check" title={a.description}>
                <input type="checkbox" checked={agents.includes(a.name)} onChange={() => toggle(agents, setAgents, a.name)} />
                <span>{a.name}</span>
              </label>
            ))}
          </div>

          <div className="setup-sec">
            <div className="setup-title">Data sources
              <button className="mini" onClick={() => setAdding((v) => !v)}>{adding ? "Cancel" : "+ add"}</button>
            </div>
            {adding && (
              <div className="addsrc">
                <label className="filebtn">{adding ? "Upload CSV / PDF" : "Upload"}<input type="file" multiple accept=".csv,.pdf,.txt,.md" onChange={addFiles} /></label>
                <div className="db-mini">
                  <input placeholder="postgresql://..." value={dbUrl} onChange={(e) => setDbUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addDb()} />
                  <button onClick={addDb}>DB</button>
                </div>
              </div>
            )}
            {sources.length === 0 && <div className="muted small">none</div>}
            {sources.map((s) => (
              <label key={s.name} className="check" title={(s.tables || []).join(", ")}>
                <input type="checkbox" checked={sourceOn(s.name)} onChange={() => toggleSource(s.name)} />
                <span>{s.name} <span className="muted small">{(s.tables || []).length}t</span></span>
              </label>
            ))}
          </div>

          <div className="setup-sec">
            <div className="setup-title">Tools & skills <span className="muted small">{tools === null ? allTools.length : tools.length}/{allTools.length}</span></div>
            {allTools.map((t) => (
              <label key={t.name} className="check" title={t.description}>
                <input type="checkbox" checked={toolOn(t.name)} onChange={() => toggleTool(t.name)} />
                <span>{t.name}</span>
              </label>
            ))}
          </div>
        </aside>
        )}

        {/* ---- Conversation column ---- */}
        <div className="center">
          <div className="messages" ref={msgRef} onScroll={() => onScroll(msgRef, stickMsg)}>
            {messages.length === 0 && <div className="muted small">Describe a defect or yield drop. The selected agents investigate in parallel.</div>}
            {messages.map((m, i) => (
              m.role === "note"
                ? <div key={i} className="msgnote">{m.text}</div>
                : <div key={i} className={"msg " + m.role + (m.pending ? " pendingq" : "") + (m.error ? " errmsg" : "")}>
                    {m.pending && <span className="ask">needs your input</span>}
                    {m.role === "assistant" ? <Md>{m.text}</Md> : m.text}
                  </div>
            ))}
            {busy && <div className="statusline"><span className="spin" /> {status || "working..."}</div>}
          </div>
          {awaiting && <div className="askbanner"><strong>The agent needs your input.</strong> Type your answer below and press Reply.</div>}
          {error && <div className="retrybar">{error}<button onClick={retry}>Retry</button></div>}
          <div className="row composer">
            <textarea ref={taRef} rows={1} value={input}
              onChange={(e) => { setInput(e.target.value); autoGrow(e.target); }}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder={busy ? "Add context while it works...  (Shift+Enter = newline)" : awaiting ? "Answer the agent..." : "Ask about a defect or yield drop...  (Shift+Enter = newline)"} />
            <button className="primary" onClick={submit}>{busy ? "Add context" : awaiting ? "Reply" : "Investigate"}</button>
          </div>
        </div>

        {/* ---- Trace column ---- */}
        {traceOpen && (
        <aside className="feed" ref={feedRef} onScroll={() => onScroll(feedRef, stickFeed)}>
          <div className="feed-title">Orchestrator <span className="muted small">- click a step</span></div>
          {events.length === 0 && <div className="muted small">steps appear here as the agents work</div>}
          <TraceLanes events={events} leadLabel="orchestrator" />
        </aside>
        )}
      </div>
    </div>
  );
}
