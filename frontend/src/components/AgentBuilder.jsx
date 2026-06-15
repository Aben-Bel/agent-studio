import React, { useState } from "react";
import { createAgent } from "../api.js";

// Simple mode: just a name + a one-line persona; the agent gets every capability
// by default so it "just works". God mode: also choose exactly which tools/skills
// it may use (a lightweight workflow definition).
export default function AgentBuilder({ caps, advanced, onCreated }) {
  const callable = [...(caps.tools || []), ...(caps.skills || [])];
  const defaults = callable.map((c) => c.name).filter((n) => n !== "echo");

  const [name, setName] = useState("my_rca_agent");
  const [persona, setPersona] = useState(
    "You are a yield-analysis assistant. Investigate the likely root cause of a defect "
    + "using the available tools, and cite the data and documents you used."
  );
  const [picked, setPicked] = useState(defaults);
  const [busy, setBusy] = useState(false);

  function toggle(n) {
    setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));
  }

  async function create() {
    setBusy(true);
    const tools = advanced ? picked : defaults;
    await createAgent({
      name: name.trim() || "my_assistant",
      description: persona.slice(0, 80),
      persona,
      tools,
    });
    setBusy(false);
    onCreated(name.trim() || "my_assistant");
  }

  return (
    <div className="agent-builder">
      <label>Name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} />

      <label>Persona - describe your assistant in a sentence or two</label>
      <textarea rows={3} value={persona} onChange={(e) => setPersona(e.target.value)} />

      {advanced && (
        <>
          <label>Capabilities it may use (its workflow)</label>
          <div className="chips">
            {callable.map((c) => (
              <button
                key={c.name}
                className={"chip" + (picked.includes(c.name) ? " on" : "")}
                onClick={() => toggle(c.name)}
                title={c.description}
              >
                {c.name}
              </button>
            ))}
          </div>
        </>
      )}

      <div className="row end">
        <button className="primary" onClick={create} disabled={busy}>
          {busy ? "Creating..." : "Create & chat"}
        </button>
      </div>
    </div>
  );
}
