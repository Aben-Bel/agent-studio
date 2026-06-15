import React, { createContext, useContext, useState } from "react";

// Lightweight i18n. Add a key to BOTH dicts; use t("key") in components.
const STRINGS = {
  en: {
    title: "Yield Analysis",
    subtitle: "Root-Cause Analysis Platform - full visibility",
    overview: "Overview",
    investigate: "Investigate",
    newInvestigation: "New investigation",
    // setup
    agents: "Agents",
    dataSources: "Data sources",
    toolsSkills: "Tools & skills",
    addAgent: "+ agent",
    add: "+ add",
    cancel: "Cancel",
    none: "none",
    hideSetup: "Hide setup",
    setup: "Setup",
    hideTrace: "Hide trace",
    trace: "Trace",
    uploadFile: "Upload CSV / PDF",
    // console
    investigateBtn: "Investigate",
    reply: "Reply",
    addContext: "Add context",
    stop: "Stop",
    retry: "Retry",
    orchestrator: "Orchestrator",
    clickStep: "click a step",
    needsInput: "The agent needs your input.",
    typeAnswer: "Type your answer below and press Reply.",
    askPlaceholder: "Ask about a defect or yield drop...  (Shift+Enter = newline)",
    answerPlaceholder: "Answer the agent...",
    contextPlaceholder: "Add context while it works...  (Shift+Enter = newline)",
    describePrompt: "Describe a defect or yield drop. The selected agents investigate in parallel.",
    stepsAppear: "steps appear here as the agents work",
    // modals
    useAgent: "Use this agent",
    toolsItMayUse: "Tools it may use",
    createAgent: "Create agent",
    name: "Name",
    persona: "Persona - what it does",
    close: "Close",
    loading: "loading...",
    // overview
    startInvestigation: "Start a root-cause investigation",
  },
  de: {
    title: "Ausbeuteanalyse",
    subtitle: "Ursachenanalyse-Plattform - volle Transparenz",
    overview: "Übersicht",
    investigate: "Untersuchen",
    newInvestigation: "Neue Untersuchung",
    agents: "Agenten",
    dataSources: "Datenquellen",
    toolsSkills: "Werkzeuge & Fähigkeiten",
    addAgent: "+ Agent",
    add: "+ hinzufügen",
    cancel: "Abbrechen",
    none: "keine",
    hideSetup: "Setup ausblenden",
    setup: "Setup",
    hideTrace: "Verlauf ausblenden",
    trace: "Verlauf",
    uploadFile: "CSV / PDF hochladen",
    investigateBtn: "Untersuchen",
    reply: "Antworten",
    addContext: "Kontext hinzufügen",
    stop: "Stopp",
    retry: "Wiederholen",
    orchestrator: "Orchestrator",
    clickStep: "Schritt anklicken",
    needsInput: "Der Agent benötigt Ihre Eingabe.",
    typeAnswer: "Geben Sie unten Ihre Antwort ein und drücken Sie Antworten.",
    askPlaceholder: "Fragen Sie nach einem Defekt oder Ausbeuteverlust...  (Umschalt+Enter = neue Zeile)",
    answerPlaceholder: "Antworten Sie dem Agenten...",
    contextPlaceholder: "Kontext hinzufügen, während es läuft...  (Umschalt+Enter = neue Zeile)",
    describePrompt: "Beschreiben Sie einen Defekt oder Ausbeuteverlust. Die ausgewählten Agenten untersuchen parallel.",
    stepsAppear: "Schritte erscheinen hier, während die Agenten arbeiten",
    useAgent: "Diesen Agenten verwenden",
    toolsItMayUse: "Verwendbare Werkzeuge",
    createAgent: "Agent erstellen",
    name: "Name",
    persona: "Persona - was er tut",
    close: "Schließen",
    loading: "wird geladen...",
    startInvestigation: "Ursachenanalyse starten",
  },
};

const Ctx = createContext({ lang: "en", t: (k) => k, setLang: () => {} });

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => localStorage.getItem("lang") || "en");
  const set = (l) => { localStorage.setItem("lang", l); setLang(l); };
  const t = (k) => (STRINGS[lang] && STRINGS[lang][k]) || STRINGS.en[k] || k;
  return <Ctx.Provider value={{ lang, t, setLang: set }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
