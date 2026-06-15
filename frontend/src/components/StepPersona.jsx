import React, { useEffect, useState } from "react";
import { getCapabilities, createAgent } from "../api.js";

export default function StepPersona({ onBack, onNext }) {
  const [caps, setCaps] = useState({ agents: [], tools: [], skills: [] });
  const [name, setName] = useState("my_comedian");
  const [persona, setPersona] = useState(
    "You are a witty, upbeat stand-up comedian. Keep jokes clean and clever."
  );
  const [description, setDescription] = useState("A custom joke agent.");
  const [picked, setPicked] = useState(["get_random_joke", "punch_up"]);

  useEffect(() => {
    getCapabilities().then(setCaps);
  }, []);

  const callable = [...caps.tools, ...caps.skills];

  function toggle(n) {
    setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));
  }

  async function create() {
    await createAgent({ name, description, persona, tools: picked });
    onNext(name);
  }

  return (
    <div className="card">
      <h2>Create a custom agent</h2>
      <p className="muted">
        A persona is the agent's system prompt. Pick which tools and skills it
        may use. This registers a new agent live; the orchestrator routes to it
        immediately.
      </p>

      <label>Name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} />

      <label>Description</label>
      <input value={description} onChange={(e) => setDescription(e.target.value)} />

      <label>Persona (system prompt)</label>
      <textarea rows={4} value={persona} onChange={(e) => setPersona(e.target.value)} />

      <label>Capabilities it can use</label>
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

      <div className="extend">
        <strong>How to extend:</strong> a developer adds a new tool by dropping
        a file in <code>tools/</code> with the <code>@tool</code> decorator, a
        skill in <code>skills/</code> with <code>@skill</code>, or an agent in{" "}
        <code>agents/</code> with <code>@agent</code>. It is auto-discovered and
        shows up in this list with no code change here.
      </div>

      <div className="row between">
        <button onClick={onBack}>Back</button>
        <button className="primary" onClick={create}>
          Create and chat
        </button>
      </div>
    </div>
  );
}
