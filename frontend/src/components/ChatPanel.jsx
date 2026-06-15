import React, { useEffect, useRef, useState } from "react";
import { runChat } from "../api.js";

// Stateful chat: every turn carries the same chat_id, so the orchestrator
// remembers the conversation, streams each step live, can PAUSE to ask the
// human (needs_human), and continues when they reply.
export default function ChatPanel({ agentName, chatId, onBack }) {
  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  const [input, setInput] = useState("Tell me a joke");
  const [busy, setBusy] = useState(false);
  const [awaiting, setAwaiting] = useState(null); // pending human question
  const feedRef = useRef(null);

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [events]);

  async function send() {
    if (!input.trim() || busy) return;
    const msg = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setEvents([]);
    setBusy(true);
    setAwaiting(null);

    let final = "";
    let paused = null;
    await runChat({ agent: agentName, message: msg, chat_id: chatId }, (ev) => {
      setEvents((e) => [...e, ev]);
      if (ev.type === "final") final = ev.data.message;
      if (ev.type === "needs_human") paused = ev.data.question;
    });

    if (paused) {
      setMessages((m) => [...m, { role: "assistant", text: paused, pending: true }]);
      setAwaiting(paused);
    } else {
      setMessages((m) => [...m, { role: "assistant", text: final }]);
    }
    setBusy(false);
  }

  return (
    <div className="card chat-wrap">
      <div className="chat-head">
        {onBack && <button onClick={onBack}>← Setup</button>}
        <span className="muted">
          Agent: <strong>{agentName}</strong>
          <span className="chatid"> · chat {chatId.slice(0, 8)}</span>
        </span>
      </div>

      <div className="chat-grid">
        <div className="messages">
          {messages.length === 0 && (
            <div className="muted small">Say hello, or ask for a joke.</div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={"msg " + m.role + (m.pending ? " pendingq" : "")}>
              {m.pending && <span className="ask">needs your input</span>}
              {m.text}
            </div>
          ))}
          {busy && <div className="msg assistant pending">working…</div>}
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
          placeholder={awaiting ? "Answer the agent…" : "Type a message…"}
        />
        <button className="primary" onClick={send} disabled={busy}>
          {awaiting ? "Reply" : "Send"}
        </button>
      </div>
    </div>
  );
}

function renderEvent(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "agent_switch":
      return `routed to ${d.agent}`;
    case "progress":
      return d.message;
    case "tool_call":
      return `${d.kind} ${d.name}(${JSON.stringify(d.args)})`;
    case "tool_result":
      return `${d.name} → ${d.result}`;
    case "needs_human":
      return `paused — asking: ${d.question}`;
    case "final":
      return "done";
    case "error":
      return d.message;
    default:
      return JSON.stringify(d);
  }
}
