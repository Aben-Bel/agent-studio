import React, { useEffect, useState } from "react";
import Dashboard from "./components/Dashboard.jsx";
import DataStep from "./components/DataStep.jsx";
import AgentBuilder from "./components/AgentBuilder.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import { getCapabilities, getRun } from "./api.js";

// ---- URL as navigation state (refresh / back / deep-link restore the view) ----
function readUrl() {
  const p = new URLSearchParams(location.search);
  return {
    admin: p.get("admin") === "1",
    view: p.get("view") || "overview",
    agent: p.get("agent") || "rca_assistant",
    chat: p.get("chat") || "",
    run: p.get("run") || "",
  };
}
function writeUrl(s) {
  const p = new URLSearchParams();
  if (s.admin) p.set("admin", "1");
  p.set("view", s.view);
  p.set("agent", s.agent);
  if (s.chat) p.set("chat", s.chat);
  if (s.run) p.set("run", s.run);
  history.replaceState(null, "", "?" + p.toString());
}
const newChatId = () =>
  crypto.randomUUID ? crypto.randomUUID() : "inv-" + Math.floor(performance.now());

export default function App() {
  const init = readUrl();
  const [admin, setAdmin] = useState(init.admin);
  const [view, setView] = useState(init.view);
  const [agent, setAgent] = useState(init.agent);
  const [chat, setChat] = useState(init.chat || newChatId());
  const [run, setRun] = useState(init.run);
  const [caps, setCaps] = useState({ agents: [], tools: [], skills: [], mcp: [], stages: [] });

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => {});
  }, [view]);
  useEffect(() => {
    writeUrl({ admin, view, agent, chat, run });
  }, [admin, view, agent, chat, run]);

  const TABS = [
    ["overview", "Overview"],
    ["data", "Data sources"],
    ["investigate", "Investigate"],
    ["capabilities", "Capabilities"],
    ...(admin ? [["agent", "Build agent"]] : []),
  ];

  function go(v) {
    setRun("");
    setView(v);
  }
  function newInvestigation(name) {
    if (name) setAgent(name);
    setChat(newChatId());
    setRun("");
    setView("investigate");
  }
  function openRun(chatId) {
    setRun(chatId);
    setView("trace");
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <h1>Yield Analysis</h1>
          <span className="sub">Root-Cause Analysis Platform · full visibility</span>
        </div>
        <div className="head-right">
          <button className="ghost" onClick={() => newInvestigation()}>New investigation</button>
          <label className="godswitch" title="Show configuration / agent building">
            <input type="checkbox" checked={admin} onChange={(e) => {
              setAdmin(e.target.checked);
              if (!e.target.checked && view === "agent") setView("overview");
            }} />
            <span className="slider" />
            <span className="godlabel">Admin</span>
          </label>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={"pill" + (view === key ? " on" : "")} onClick={() => go(key)}>
            {label}
          </button>
        ))}
      </nav>

      <main>
        {view === "overview" && <Dashboard caps={caps} onGo={go} onOpenRun={openRun} />}
        {view === "data" && <DataStep />}
        {view === "capabilities" && <CapabilitiesView caps={caps} />}
        {view === "investigate" && (
          <ChatPanel agentName={agent} chatId={chat} onBack={() => go("overview")} />
        )}
        {view === "agent" && admin && (
          <div className="card">
            <h2>Build an investigation agent</h2>
            <p className="muted">
              Write a persona and choose exactly which tools it may use. Registered live and
              routable immediately — the real RCA reasoning agent will be built on this seam.
            </p>
            <AgentBuilder caps={caps} advanced onCreated={newInvestigation} />
          </div>
        )}
        {view === "trace" && <RunTrace chatId={run} onBack={() => go("overview")} />}
      </main>
    </div>
  );
}

function CapabilitiesView({ caps }) {
  const Section = ({ title, items, render }) => (
    <div className="capsec">
      <div className="capsec-title">{title} <span className="count">{items.length}</span></div>
      {items.length === 0 && <div className="muted small">none</div>}
      <div className="caplist">{items.map(render)}</div>
    </div>
  );
  return (
    <div className="card">
      <h2>Everything the platform can do</h2>
      <p className="muted">
        Auto-discovered from the backend. Drop a file in <code>agents/</code>, <code>tools/</code>,{" "}
        <code>skills/</code>, <code>mcp/</code>, or <code>pipeline/</code> (any subfolder) and it
        shows up here — no shared file to edit, no merge conflicts.
      </p>
      <Section title="Agents" items={caps.agents} render={(a) => (
        <div key={a.name} className="capitem"><strong>{a.name}</strong>
          <span className="muted small"> {a.description}</span></div>
      )} />
      <Section title="Tools" items={caps.tools} render={(t) => (
        <div key={t.name} className="capitem">
          <code>{t.name}</code>
          {t.owner && <span className="ownertag">{t.owner}</span>}
          {t.version && <span className="vertag">v{t.version}</span>}
          <span className="muted small"> {t.description}</span>
        </div>
      )} />
      <Section title="Skills" items={caps.skills} render={(s) => (
        <div key={s.name} className="capitem"><code>{s.name}</code>
          <span className="muted small"> {s.description}</span></div>
      )} />
      <Section title="MCP servers" items={caps.mcp || []} render={(m) => (
        <div key={m.name} className="capitem"><code>{m.name}</code>
          <span className="muted small"> {m.description}</span></div>
      )} />
      <Section title="Pipeline stages (upload → …)" items={caps.stages || []} render={(s) => (
        <div key={s.name} className="capitem"><code>{s.order}. {s.name}</code>
          <span className="muted small"> {s.description}</span></div>
      )} />
    </div>
  );
}

function RunTrace({ chatId, onBack }) {
  const [trace, setTrace] = useState(null);
  useEffect(() => {
    getRun(chatId).then(setTrace).catch(() => setTrace({ steps: [] }));
  }, [chatId]);
  return (
    <div className="card">
      <div className="chat-head">
        <button onClick={onBack}>← Overview</button>
        <span className="muted">Investigation trace · <strong>{chatId.slice(0, 8)}</strong></span>
      </div>
      {!trace && <div className="muted small">loading…</div>}
      {trace && trace.steps.length === 0 && <div className="muted small">no steps recorded</div>}
      <div className="trace">
        {trace?.steps.map((s) => (
          <div key={s.seq} className={"ev " + s.type}>
            <span className="tag">{s.type}</span>
            <span className="evtext">{traceText(s)}</span>
            <span className="muted small tracets">{(s.ts || "").replace("T", " ").slice(11, 19)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function traceText(s) {
  const d = s.data || {};
  switch (s.type) {
    case "agent_switch": return `routed to ${d.agent}`;
    case "user_message": return d.text;
    case "tool_call": return `${d.name}(${JSON.stringify(d.args || {})})`;
    case "tool_result": return `${d.name} → ${d.result}`;
    case "needs_human": return `asked: ${d.question}`;
    case "context_added": return `context: ${d.text}`;
    case "final": return d.message;
    case "error": return d.message;
    default: return JSON.stringify(d);
  }
}
