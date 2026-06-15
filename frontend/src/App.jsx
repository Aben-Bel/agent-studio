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
    ...(admin ? [["agent", "Build agent"]] : []),
  ];

  return (
    <div className={"app" + (view === "investigate" ? " app-wide" : "")}>
      <header>
        <div className="brand">
          <h1>Yield Analysis</h1>
          <span className="sub">Root-Cause Analysis Platform - full visibility</span>
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
        {view === "investigate" && (
          <ChatPanel key={chat} caps={caps} chatId={chat} initialAgents={agents} onBack={() => go("overview")} />
        )}
        {view === "agent" && admin && (
          <div className="card">
            <h2>Build an investigation agent</h2>
            <p className="muted">
              Write a persona and choose which tools it may use. Registered live and routable
              immediately - the same seam every specialist agent is built on.
            </p>
            <AgentBuilder caps={caps} advanced onCreated={newInvestigation} />
          </div>
        )}
      </main>
    </div>
  );
}
