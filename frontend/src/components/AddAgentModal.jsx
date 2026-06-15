import React, { useState } from "react";
import Modal from "./Modal.jsx";
import { createAgent } from "../api.js";

// Create a custom agent from the Setup panel. It registers live and shows up in
// the agent list immediately (after caps refresh).
export default function AddAgentModal({ caps, onClose, onCreated }) {
  const callable = [...(caps.tools || []), ...(caps.skills || [])];
  const [name, setName] = useState("");
  const [persona, setPersona] = useState("");
  const [picked, setPicked] = useState(callable.map((c) => c.name).filter((n) => n !== "consult_agent"));
  const [busy, setBusy] = useState(false);
  const toggle = (n) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));

  async function create() {
    const nm = name.trim().replace(/\s+/g, "_").toLowerCase();
    if (!nm) return;
    setBusy(true);
    await createAgent({
      name: nm,
      description: (persona || "custom agent").slice(0, 80),
      persona: persona || "You are a yield-analysis agent. Investigate and cite your data.",
      tools: picked,
    }).catch(() => {});
    setBusy(false);
    onCreated(nm);
  }

  return (
    <Modal title="Add an agent" onClose={onClose}>
      <label>Name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. defect_classifier" />
      <label>Persona - what it does</label>
      <textarea rows={3} value={persona} onChange={(e) => setPersona(e.target.value)}
        placeholder="You are a ... Investigate ... cite the data you use." />
      <label>Tools it may use</label>
      <div className="chips">
        {callable.map((c) => (
          <button key={c.name} className={"chip" + (picked.includes(c.name) ? " on" : "")}
            title={c.description} onClick={() => toggle(c.name)}>{c.name}</button>
        ))}
      </div>
      <div className="row end">
        <button className="primary" disabled={busy || !name.trim()} onClick={create}>
          {busy ? "Creating..." : "Create agent"}
        </button>
      </div>
    </Modal>
  );
}
