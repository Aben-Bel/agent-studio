import React, { useEffect, useState } from "react";
import Dashboard from "./components/Dashboard.jsx";
import DataStep from "./components/DataStep.jsx";
import AgentBuilder from "./components/AgentBuilder.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import { getCapabilities } from "./api.js";

// ---- URL is the source of navigation state. Back/forward/refresh/deep-link all
// restore the exact view. State changes push a history entry; popstate reads it back.
function readUrl() {
  const p = new URLSearchParams(location.search);
  return {
    admin: p.get("admin") === "1",
    view: p.get("view") || "overview",
    agents: (p.get("agents") || "").split(",").filter(Boolean),
    chat: p.get("chat") || "",
  };
}
function urlFor(s) {
  const p = new URLSearchParams();
  if (s.admin) p.set("admin", "1");
  p.set("view", s.view);
  if (s.agents && s.agents.length) p.set("agents", s.agents.join(","));
  if (s.chat) p.set("chat", s.chat);
  return "?" + p.toString();
}
const newChatId = () =>
  crypto.randomUUID ? crypto.randomUUID() : "inv-" + Math.floor(performance.now());

export default function App() {
  const [nav, setNav] = useState(() => {
    const init = readUrl();
    return { ...init, chat: init.chat || newChatId() };
  });
  const [caps, setCaps] = useState({ agents: [], tools: [], skills: [], mcp: [], stages: [] });

  useEffect(() => { getCapabilities().then(setCaps).catch(() => {}); }, [nav.view]);
  useEffect(() => {
    const onPop = () => setNav((n) => ({ ...n, ...readUrl() }));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function goTo(partial) {
    setNav((n) => {
      const next = { ...n, ...partial };
      history.pushState(null, "", urlFor(next));
      return next;
    });
  }
  const go = (view) => goTo({ view });
  const newInvestigation = (name) =>
    goTo({ view: "investigate", chat: newChatId(), agents: name && name !== "team" ? [name] : [] });
  const openRun = (chatId) => goTo({ view: "investigate", chat: chatId, agents: [] });

  const { admin, view, agents, chat } = nav;
  const TABS = [
    ["overview", "Overview"], ["data", "Data sources"], ["investigate", "Investigate"],
    ["capabilities", "Capabilities"], ...(admin ? [["agent", "Build agent"]] : []),
  ];

  return (
    <div className="app">
      <header>
        <div className="brand">
          <h1>Yield Analysis</h1>
          <span className="sub">Root-Cause Analysis Platform · full visibility</span>
        </div>
        <div className="head-right">
          <button className="ghost" onClick={() => newInvestigation("team")}>New investigation</button>
          <label className="godswitch" title="Show configuration / agent building">
            <input type="checkbox" checked={admin} onChange={(e) =>
              goTo({ admin: e.target.checked, view: !e.target.checked && view === "agent" ? "overview" : view })} />
            <span className="slider" />
            <span className="godlabel">Admin</span>
          </label>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={"pill" + (view === key ? " on" : "")} onClick={() => go(key)}>{label}</button>
        ))}
      </nav>

      <main>
        {view === "overview" && <Dashboard caps={caps} onGo={go} onOpenRun={openRun} onPickAgent={newInvestigation} />}
        {view === "data" && <DataStep />}
        {view === "capabilities" && <CapabilitiesView caps={caps} onPickAgent={newInvestigation} />}
        {view === "investigate" && (
          <ChatPanel key={chat} caps={caps} chatId={chat} initialAgents={agents} onBack={() => go("overview")} />
        )}
        {view === "agent" && admin && (
          <div className="card">
            <h2>Build an investigation agent</h2>
            <p className="muted">
              Write a persona and choose which tools it may use. Registered live and routable
              immediately — the same seam every specialist agent is built on.
            </p>
            <AgentBuilder caps={caps} advanced onCreated={newInvestigation} />
          </div>
        )}
      </main>
    </div>
  );
}

function CapabilitiesView({ caps, onPickAgent }) {
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
      <Section title="Agents — click to investigate with one" items={caps.agents} render={(a) => (
        <div key={a.name} className="capitem agentpick" onClick={() => onPickAgent && onPickAgent(a.name)}>
          <strong>{a.name}</strong>
          <span className="muted small"> {a.description}</span>
          <span className="pickhint">investigate →</span>
        </div>
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
