import React, { useEffect, useState } from "react";
import { getSources, getProcessStatus, getCapabilities, getRuns } from "../api.js";
import { prettyName } from "../format.js";

// Overview = full visibility at a glance: what data is connected, what's been
// ingested, what the platform can do, and every investigation that has run.
export default function Dashboard({ caps, onOpenRun, onGo, onPickAgent }) {
  const [sources, setSources] = useState([]);
  const [pipe, setPipe] = useState({ counts: {}, pending: 0, stages: [] });
  const [runs, setRuns] = useState([]);

  async function refresh() {
    try {
      const [s, p, r] = await Promise.all([getSources(), getProcessStatus(), getRuns()]);
      setSources(s.sources || []);
      setPipe(p || {});
      setRuns(r.runs || []);
    } catch {
      /* ignore */
    }
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const tableCount = sources.reduce((n, s) => n + (s.tables?.length || 0), 0);
  const docDone = pipe.counts?.done || 0;

  return (
    <div className="dash">
      <div className="stat-grid">
        <Stat label="Data sources" value={sources.length} sub={`${tableCount} tables`} />
        <Stat label="Documents indexed" value={docDone} sub={pipe.pending ? `${pipe.pending} pending` : "RAG ready"} />
        <Stat label="Tools" value={(caps.tools || []).length} sub={`${(caps.stages || []).length} pipeline stages`} />
        <Stat label="Investigations" value={runs.length} sub="audit trail" onClick={() => onGo("investigate")} />
      </div>

      <div className="card dash-cta">
        <div>
          <h2>Start a root-cause investigation</h2>
          <p className="muted">
            Ask about a defect or yield drop. The lead agent recruits specialists as needed;
            every step - each tool call, the data and documents it touches - streams live and is recorded.
          </p>
        </div>
        <button className="primary" onClick={() => onPickAgent("team")}>New investigation</button>
      </div>

      <div className="card">
        <div className="sources-title">Investigate - run the whole team in parallel, or pick one agent</div>
        <div className="team">
          <button className="agentcard team-card" onClick={() => onPickAgent && onPickAgent("team")}>
            <div className="agentcard-name">Team (parallel)</div>
            <div className="agentcard-desc">Fire all specialists at once and synthesize one conclusion. Default mode.</div>
            <div className="agentcard-tools">{(caps.agents || []).filter((a) => !(a.tools || []).includes("consult_agent")).length} specialists</div>
          </button>
          {(caps.agents || []).map((a) => (
            <button key={a.name} className="agentcard" onClick={() => onPickAgent && onPickAgent(a.name)}>
              <div className="agentcard-name">{prettyName(a.name)}</div>
              <div className="agentcard-desc" title={a.description}>{a.description}</div>
              <div className="agentcard-tools">{(a.tools || []).length} tools</div>
            </button>
          ))}
        </div>
      </div>

      <div className="dash-cols">
        <div className="card">
          <div className="sources-title">Connected data</div>
          {sources.length === 0 && <div className="muted small">none yet - add data</div>}
          {sources.map((s) => (
            <div key={s.name} className="src">
              <span className="src-name">{s.name}</span>
              <span className="src-dialect">{s.dialect}</span>
              <span className="src-tables">{s.tables.length ? s.tables.join(", ") : "(no tables)"}</span>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="sources-title">Recent investigations</div>
          {runs.length === 0 && <div className="muted small">no runs yet</div>}
          {runs.slice(0, 8).map((r) => (
            <div key={r.chat_id} className="runrow" onClick={() => onOpenRun(r.chat_id, r.agent)}>
              <span className={"runstatus " + r.status}>{r.status}</span>
              <span className="runagent">{prettyName(r.agent)}</span>
              <span className="runsteps">{r.steps} steps</span>
              <span className="muted small runtime">{(r.updated || "").replace("T", " ").slice(0, 16)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, onClick }) {
  const inner = (<>
    <div className="stat-value">{value}</div>
    <div className="stat-label">{label}</div>
    <div className="stat-sub">{sub}</div>
  </>);
  return onClick
    ? <button className="stat clickable" onClick={onClick}>{inner}</button>
    : <div className="stat">{inner}</div>;
}
