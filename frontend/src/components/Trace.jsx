import React, { useState } from "react";
import { prettyName } from "../format.js";
import { useI18n } from "../i18n.jsx";
import FriendlyResult from "./FriendlyResult.jsx";

// Read a text field in the active language. The backend pairs every prose field
// X into X_i18n = {en, de}; we prefer that, falling back to the raw field (older
// events / not-yet-paired). This is what makes the whole trace flip on a toggle.
export function tx(d, field, lang) {
  const m = d && d[field + "_i18n"];
  return (m && (m[lang] || m.en)) || (d ? d[field] : "") || "";
}

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
  // Each agent lane is an accordion: lead stays open, recruited agents start
  // collapsed so a parallel investigation reads as a tidy list you can unfold.
  const [open, setOpen] = useState(lead);
  return (
    <div className={"lane" + (lead ? " lead" : "") + " " + status + (open ? "" : " collapsed")}>
      <div className="lane-head click" onClick={() => setOpen(!open)}>
        <span className="lane-name">
          <span className="lane-caret">{open ? "▾" : "▸"}</span>
          {prettyName(name)}
        </span>
        <span className={"lane-status " + status}>{status === "working" ? "working..." : status}</span>
      </div>
      {open && dispatched && (
        <div className="lane-dispatch">
          routed to {(dispatched.data.agents || []).map(prettyName).join(", ") || "(none)"}
          {(dispatched.data.skipped || []).length > 0 &&
            <span className="muted"> - skipped {(dispatched.data.skipped || []).map(prettyName).join(", ")} (not needed)</span>}
        </div>
      )}
      {open && (
        <div className="lane-steps">
          {steps.length === 0 && <div className="muted small">-</div>}
          {steps.map((e, i) => <TraceEvent key={i} ev={e} />)}
        </div>
      )}
    </div>
  );
}

// One step in the orchestrator trace. Click to expand full args / result - this
// is the transparency surface. Recruited-agent steps are indented (depth).
export default function TraceEvent({ ev }) {
  const { lang } = useI18n();
  const [open, setOpen] = useState(false);
  const d = ev.data || {};
  const depth = d.depth || 0;
  const expandable = ["tool_call", "tool_result", "thinking", "final", "needs_human", "context_added", "error", "user_message"].includes(ev.type);

  let head = "";
  if (ev.type === "agent_switch") {
    head = d.role === "recruited" ? `recruited ${prettyName(d.agent)}`
      : d.role === "resumed" ? `back to ${prettyName(d.agent)}` : `lead ${prettyName(d.agent)}`;
  } else if (ev.type === "progress") head = tx(d, "message", lang);
  else if (ev.type === "thinking") head = tx(d, "text", lang).replace(/\s+/g, " ").slice(0, 80);
  else if (ev.type === "tool_call") head = d.kind === "agent" ? `recruit ${prettyName((d.args || {}).agent || "")}` : prettyName(d.name);
  else if (ev.type === "tool_result") head = prettyName(d.name);
  else if (ev.type === "user_message") head = tx(d, "text", lang);
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
      {open && <div className="evdetail-wrap">{detail(ev, lang)}</div>}
    </div>
  );
}

// Structured tool results/args render as friendly rows (FriendlyResult parses
// JSON / Python-dict and falls back to raw text). Prose fields stay as <pre>.
function detail(ev, lang) {
  const d = ev.data || {};
  const pre = (s) => <pre className="evdetail">{s || ""}</pre>;
  switch (ev.type) {
    case "thinking": return pre(tx(d, "text", lang));
    case "tool_call":
      return Object.keys(d.args || {}).length
        ? <FriendlyResult result={JSON.stringify(d.args || {})} />
        : pre("(no arguments)");
    case "tool_result": return <FriendlyResult result={tx(d, "result", lang)} />;
    case "final": return pre(tx(d, "message", lang));
    case "user_message": return pre(tx(d, "text", lang));
    case "needs_human": return pre(tx(d, "question", lang));
    case "context_added": return pre(tx(d, "text", lang));
    case "error": return pre(tx(d, "message", lang));
    default: return null;
  }
}
