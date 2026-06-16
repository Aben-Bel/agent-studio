import React, { useState, useMemo } from "react";
import Modal from "./Modal.jsx";
import ToolTip from "./ToolTip.jsx";
import { useI18n } from "../i18n.jsx";
import { createAgent } from "../api.js";

// Create a custom agent from the Setup panel. It registers live and shows up in
// the agent list immediately (after caps refresh). Includes optional routing
// guidance (when/how/use-for/not-for) and a SEARCHABLE, SCROLLABLE tool picker so
// the chip list can't overflow the modal as the tool catalogue grows.
export default function AddAgentModal({ caps, onClose, onCreated }) {
  const { t, lang } = useI18n();
  const pick = (m, f) => (m && (m[lang] || m.en)) || f || "";
  const callable = useMemo(() => [...(caps.tools || []), ...(caps.skills || [])].map((c) => ({
    ...c,
    description: pick(c.description_i18n, c.description),
    limits: pick(c.limits_i18n, c.limits),
  })), [caps, lang]); // eslint-disable-line

  const [name, setName] = useState("");
  const [persona, setPersona] = useState("");
  const [whenToUse, setWhenToUse] = useState("");
  const [whatToUseFor, setWhatToUseFor] = useState("");
  const [whatNotToUseFor, setWhatNotToUseFor] = useState("");
  const [toolQuery, setToolQuery] = useState("");
  const [picked, setPicked] = useState(callable.map((c) => c.name).filter((n) => n !== "consult_agent"));
  const [busy, setBusy] = useState(false);
  const toggle = (n) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));

  const filtered = useMemo(() => {
    const q = toolQuery.trim().toLowerCase();
    if (!q) return callable;
    return callable.filter((c) =>
      c.name.toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q));
  }, [callable, toolQuery]);

  async function create() {
    const nm = name.trim().replace(/\s+/g, "_").toLowerCase();
    if (!nm) return;
    setBusy(true);
    await createAgent({
      name: nm,
      description: (persona || "custom agent").slice(0, 80),
      persona: persona || "You are a yield-analysis agent. Investigate and cite your data.",
      tools: picked,
      when_to_use: whenToUse.trim(),
      what_to_use_for: whatToUseFor.trim(),
      what_not_to_use_for: whatNotToUseFor.trim(),
    }).catch(() => {});
    setBusy(false);
    onCreated(nm);
  }

  return (
    <Modal title={t("createAgent")} onClose={onClose}>
      <label>{t("name")}</label>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. defect_classifier" />

      <label>{t("persona")}</label>
      <textarea rows={3} value={persona} onChange={(e) => setPersona(e.target.value)}
        placeholder="You are a ... Investigate ... cite the data you use." />

      <label>{t("whenToUse")}</label>
      <input value={whenToUse} onChange={(e) => setWhenToUse(e.target.value)}
        placeholder="e.g. spec-limit compliance and measurement-driven yield questions" />

      <label>{t("whatToUseFor")}</label>
      <input value={whatToUseFor} onChange={(e) => setWhatToUseFor(e.target.value)}
        placeholder="e.g. breach % per step, measurement-driven yield impact" />

      <label>{t("whatNotToUseFor")}</label>
      <input value={whatNotToUseFor} onChange={(e) => setWhatNotToUseFor(e.target.value)}
        placeholder="e.g. NOT FMEA text or wafer images" />

      <label>{t("toolsItMayUse")} <span className="muted small">{picked.length}/{callable.length}</span></label>
      <input className="tool-search" value={toolQuery} onChange={(e) => setToolQuery(e.target.value)}
        placeholder={t("searchTools")} />
      <div className="chips chips-scroll">
        {filtered.map((c) => (
          <ToolTip key={c.name} name={c.name} cap={c.description} cannot={c.limits}>
            <button className={"chip" + (picked.includes(c.name) ? " on" : "")}
              onClick={() => toggle(c.name)}>{c.name}</button>
          </ToolTip>
        ))}
        {filtered.length === 0 && <span className="muted small">{t("none")}</span>}
      </div>

      <div className="row end">
        <button className="primary" disabled={busy || !name.trim()} onClick={create}>
          {busy ? t("loading") : t("createAgent")}
        </button>
      </div>
    </Modal>
  );
}
