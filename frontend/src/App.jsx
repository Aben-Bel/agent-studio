import React, { useEffect, useState } from "react";
import Dashboard from "./components/Dashboard.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import { useI18n } from "./i18n.jsx";
import { getCapabilities } from "./api.js";

// ---- URL is the source of navigation state. Back/forward/refresh/deep-link all
// restore the exact view. State changes push a history entry; popstate reads it back.
function readUrl() {
  const p = new URLSearchParams(location.search);
  return {
    view: p.get("view") || "overview",
    agents: (p.get("agents") || "").split(",").filter(Boolean),
    chat: p.get("chat") || "",
  };
}
function urlFor(s) {
  const p = new URLSearchParams();
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
  const refreshCaps = () => getCapabilities().then(setCaps).catch(() => {});

  // Light/dark theme: source of truth is data-theme on <html>; persisted across reloads.
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("theme", theme); }, [theme]);

  useEffect(() => { refreshCaps(); }, [nav.view]); // eslint-disable-line
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

  const { t, lang, setLang } = useI18n();
  const { view, agents, chat } = nav;
  const TABS = [["overview", t("overview")], ["investigate", t("investigate")]];

  return (
    <div className={"app app-wide" + (view === "investigate" ? " app-fixed" : "")}>
      <header>
        <div className="brand">
          <h1>{t("title")}</h1>
          <span className="sub">{t("subtitle")}</span>
        </div>
        <div className="head-right">
          <button className="primary" onClick={() => newInvestigation("team")}>{t("newInvestigation")}</button>
          <button className="themetoggle" title={theme === "dark" ? "Switch to light" : "Switch to dark"}
            onClick={() => setTheme((x) => (x === "dark" ? "light" : "dark"))}>
            {theme === "dark" ? "☀" : "☾"}
          </button>
          <div className="langwrap">
            <div className="langtoggle">
              <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>EN</button>
              <button className={lang === "de" ? "on" : ""} onClick={() => setLang("de")}>DE</button>
            </div>
          </div>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={"pill" + (view === key ? " on" : "")} onClick={() => go(key)}>{label}</button>
        ))}
      </nav>

      <main>
        {view === "overview" && <Dashboard caps={caps} onGo={go} onOpenRun={openRun} onPickAgent={newInvestigation} />}
        {view === "investigate" && (
          <ChatPanel key={chat} caps={caps} chatId={chat} initialAgents={agents}
            onBack={() => go("overview")} refreshCaps={refreshCaps} />
        )}
      </main>
    </div>
  );
}
