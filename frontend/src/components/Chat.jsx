import React, { useRef, useState } from "react";
import { runChat } from "../api.js";
import { prettyName } from "../format.js";

export default function Chat({ agentName, onBack }) {
  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  const [input, setInput] = useState("Tell me a joke");
  const [busy, setBusy] = useState(false);
  const feedRef = useRef(null);

  async function send() {
    if (!input.trim() || busy) return;
    const msg = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setEvents([]);
    setBusy(true);

    let final = "";
    await runChat({ agent: agentName, message: msg, history: [] }, (ev) => {
      setEvents((e) => [...e, ev]);
      if (ev.type === "final") final = ev.data.message;
      if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
    });

    setMessages((m) => [...m, { role: "assistant", text: final }]);
    setBusy(false);
  }

  return (
    <div className="card chat-wrap">
      <div className="chat-head">
        <button onClick={onBack}>Back</button>
        <span className="muted">Agent: <strong>{agentName}</strong></span>
      </div>

      <div className="chat-grid">
        <div className="messages">
          {messages.map((m, i) => (
            <div key={i} className={"msg " + m.role}>
              {m.text}
            </div>
          ))}
          {busy && <div className="msg assistant pending">working...</div>}
        </div>

        <aside className="feed" ref={feedRef}>
          <div className="feed-title">Orchestrator</div>
          {events.length === 0 && <div className="muted small">live steps appear here</div>}
          {events.map((ev, i) => (
            <div key={i} className={"ev " + ev.type}>
              <span className="tag">{ev.type}</span>
              <span className="evtext">{renderEvent(ev)}</span>
            </div>
          ))}
        </aside>
      </div>

      <div className="row composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask for a joke..."
        />
        <button className="primary" onClick={send} disabled={busy}>
          Send
        </button>
      </div>
    </div>
  );
}

function renderEvent(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "agent_switch":
      return `routed to ${prettyName(d.agent)}`;
    case "progress":
      return d.message;
    case "tool_call":
      return `${d.kind} ${prettyName(d.name)}(${JSON.stringify(d.args)})`;
    case "tool_result":
      return `${prettyName(d.name)} -> ${d.result}`;
    case "final":
      return "done";
    case "error":
      return d.message;
    default:
      return JSON.stringify(d);
  }
}
