import React, { useEffect, useState } from "react";
import DataStep from "./components/DataStep.jsx";
import AgentBuilder from "./components/AgentBuilder.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import { getCapabilities } from "./api.js";

// ---- URL as navigation state (refresh / back / deep-link all restore the view)
function readUrl() {
  const p = new URLSearchParams(location.search);
  return {
    god: p.get("god") === "1",
    view: p.get("view") || "data", // data | agent | capabilities | chat
    agent: p.get("agent") || "joker",
    chat: p.get("chat") || "",
  };
}
function writeUrl(s) {
  const p = new URLSearchParams();
  if (s.god) p.set("god", "1");
  p.set("view", s.view);
  p.set("agent", s.agent);
  if (s.chat) p.set("chat", s.chat);
  history.replaceState(null, "", "?" + p.toString());
}
const newChatId = () =>
  crypto.randomUUID ? crypto.randomUUID() : "chat-" + Math.floor(performance.now());

const SIMPLE_STEPS = [
  ["data", "Add data"],
  ["agent", "Persona"],
  ["chat", "Chat"],
];
const GOD_TABS = [
  ["data", "Data sources"],
  ["agent", "Build agent"],
  ["capabilities", "Capabilities"],
  ["chat", "Chat"],
];

export default function App() {
  const init = readUrl();
  const [god, setGod] = useState(init.god);
  const [view, setView] = useState(init.view === "capabilities" && !init.god ? "data" : init.view);
  const [agent, setAgent] = useState(init.agent);
  const [chat, setChat] = useState(init.chat || newChatId());
  const [caps, setCaps] = useState({ agents: [], tools: [], skills: [], mcp: [] });

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => {});
  }, [view]);
  useEffect(() => {
    writeUrl({ god, view, agent, chat });
  }, [god, view, agent, chat]);

  function startChatWith(name) {
    setAgent(name);
    setChat(newChatId());
    setView("chat");
  }
  function chatNow() {
    setChat(newChatId());
    setView("chat");
  }

  const tabs = god ? GOD_TABS : SIMPLE_STEPS;

  return (
    <div className="app">
      <header>
        <div className="brand">
          <h1>Agent Studio</h1>
          <span className="sub">build a chat assistant on your own data</span>
        </div>
        <div className="head-right">
          <button className="ghost" onClick={chatNow}>Chat now</button>
          <label className="godswitch" title="Turn on to configure everything">
            <input type="checkbox" checked={god} onChange={(e) => {
              setGod(e.target.checked);
              if (!e.target.checked && view === "capabilities") setView("data");
            }} />
            <span className="slider" />
            <span className="godlabel">God mode</span>
          </label>
        </div>
      </header>

      <nav className="tabs">
        {tabs.map(([key, label], i) => (
          <button
            key={key}
            className={"pill" + (view === key ? " on" : "")}
            onClick={() => setView(key)}
          >
            {god ? "" : `${i + 1}. `}{label}
          </button>
        ))}
      </nav>

      <main>
        {view === "data" && (
          <DataStep
            onContinue={god ? null : () => setView("agent")}
            continueLabel="Next: persona"
          />
        )}

        {view === "agent" && (
          <div className="card">
            <h2>{god ? "Build an agent" : "Describe your assistant"}</h2>
            <p className="muted">
              {god
                ? "Write a persona and pick exactly which tools and skills it may use."
                : "A persona is all it takes — your assistant gets every capability automatically."}
            </p>
            <AgentBuilder caps={caps} advanced={god} onCreated={startChatWith} />
          </div>
        )}

        {view === "capabilities" && god && <CapabilitiesView caps={caps} />}

        {view === "chat" && (
          <ChatPanel
            agentName={agent}
            chatId={chat}
            onBack={() => setView(god ? "agent" : "data")}
          />
        )}
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
        Auto-discovered from the backend. Drop a new file in <code>agents/</code>,{" "}
        <code>tools/</code>, <code>skills/</code>, or <code>mcp/</code> (any subfolder)
        and it shows up here — no shared file to edit, no merge conflicts.
      </p>
      <Section title="Agents" items={caps.agents} render={(a) => (
        <div key={a.name} className="capitem">
          <strong>{a.name}</strong><span className="muted small"> {a.description}</span>
        </div>
      )} />
      <Section title="Tools" items={caps.tools} render={(t) => (
        <div key={t.name} className="capitem"><code>{t.name}</code>
          <span className="muted small"> {t.description}</span></div>
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
