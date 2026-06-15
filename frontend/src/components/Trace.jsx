import React, { useState } from "react";

// Group the flat event stream into per-agent LANES so a parallel investigation
// is readable: the orchestrator's dispatch/conclusion on top, then one card per
// agent showing exactly what it did. This is the usable trace.
export function TraceLanes({ events, leadLabel = "orchestrator" }) {
  const groups = {};
  const order = [];
  for (const ev of events) {
    const scope = ev.data?.agent_scope || leadLabel;
    if (!(scope in groups)) { groups[scope] = []; order.push(scope); }
    groups[scope].push(ev);
  }
  // lead lane first, then the rest
  order.sort((a, b) => (a === leadLabel ? -1 : b === leadLabel ? 1 : 0));
  return (
    <div className="lanes">
      {order.map((name) => <Lane key={name} name={name} lead={name === leadLabel} events={groups[name]} />)}
    </div>
  );
}

function Lane({ name, lead, events }) {
  const steps = events.filter((e) => e.type !== "agent_switch");
  const dispatched = events.find((e) => e.type === "agent_switch" && e.data?.role === "dispatch");
  const errored = events.some((e) => e.type === "error");
  const done = events.some((e) => e.type === "final");
  const status = errored ? "error" : done ? "done" : "working";
  return (
    <div className={"lane" + (lead ? " lead" : "") + " " + status}>
      <div className="lane-head">
        <span className="lane-name">{name}</span>
        <span className={"lane-status " + status}>{status === "working" ? "working..." : status}</span>
      </div>
      {dispatched && (
        <div className="lane-dispatch">
          routed to {(dispatched.data.agents || []).join(", ") || "(none)"}
          {(dispatched.data.skipped || []).length > 0 &&
            <span className="muted"> - skipped {dispatched.data.skipped.join(", ")} (not needed)</span>}
        </div>
      )}
      <div className="lane-steps">
        {steps.length === 0 && <div className="muted small">-</div>}
        {steps.map((e, i) => <TraceEvent key={i} ev={e} />)}
      </div>
    </div>
  );
}

// One step in the orchestrator trace. Click to expand full args / result - this
// is the transparency surface. Recruited-agent steps are indented (depth).
export default function TraceEvent({ ev }) {
  const [open, setOpen] = useState(false);
  const d = ev.data || {};
  const depth = d.depth || 0;
  const expandable = ["tool_call", "tool_result", "thinking", "final", "needs_human", "context_added", "error", "user_message"].includes(ev.type);

  let head = "";
  if (ev.type === "agent_switch") {
    head = d.role === "recruited" ? `recruited ${d.agent}`
      : d.role === "resumed" ? `back to ${d.agent}` : `lead ${d.agent}`;
  } else if (ev.type === "progress") head = d.message;
  else if (ev.type === "thinking") head = (d.text || "").replace(/\s+/g, " ").slice(0, 80);
  else if (ev.type === "tool_call") head = d.kind === "agent" ? `recruit ${(d.args || {}).agent || ""}` : d.name;
  else if (ev.type === "tool_result") head = `${d.name}`;
  else if (ev.type === "user_message") head = d.text;
  else if (ev.type === "needs_human") head = "needs human";
  else if (ev.type === "context_added") head = "context added";
  else if (ev.type === "final") head = depth ? "specialist done" : "conclusion";
  else if (ev.type === "error") head = "error";

  const tag = ev.type === "agent_switch" ? (d.role || "agent") : ev.type.replace(/_/g, " ");

  return (
    <div className={"ev " + ev.type + (depth ? " nested" : "")} style={depth ? { marginLeft: 12 } : undefined}>
      <div className={"evhead" + (expandable ? " click" : "")} onClick={() => expandable && setOpen(!open)}>
        <span className="tag">{tag}</span>
        <span className="evtext">{head}</span>
        {ev.ts && <span className="muted small evts">{(ev.ts || "").slice(11, 19)}</span>}
        {expandable && <span className="caret">{open ? "-" : "+"}</span>}
      </div>
      {open && <pre className="evdetail">{detail(ev)}</pre>}
    </div>
  );
}

function detail(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "thinking": return d.text || "";
    case "tool_call": return "arguments:\n" + JSON.stringify(d.args || {}, null, 2);
    case "tool_result": return "result:\n" + (d.result ?? "");
    case "final": return d.message || "";
    case "user_message": return d.text || "";
    case "needs_human": return d.question || "";
    case "context_added": return d.text || "";
    case "error": return d.message || "";
    default: return "";
  }
}
