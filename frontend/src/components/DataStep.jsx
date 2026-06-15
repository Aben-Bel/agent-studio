import React, { useEffect, useState } from "react";
import { uploadFiles, connectDb, getSources } from "../api.js";

// Used in BOTH Simple mode and God mode: upload many CSV/PDF files and connect
// database URLs. Everyone needs data; only the technical knobs are God-mode.
export default function DataStep({ onContinue, continueLabel = "Continue" }) {
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const [dbUrl, setDbUrl] = useState("");
  const [dbName, setDbName] = useState("");
  const [dbMsg, setDbMsg] = useState(null);
  const [sources, setSources] = useState([]);

  async function refreshSources() {
    try {
      const s = await getSources();
      setSources(s.sources || []);
    } catch {
      /* ignore */
    }
  }
  useEffect(() => {
    refreshSources();
  }, []);

  async function handleFiles(e) {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setBusy(true);
    try {
      const r = await uploadFiles(files);
      setResults((prev) => [...(r.results || []), ...prev]);
      await refreshSources();
    } catch (err) {
      setResults((prev) => [{ name: "(upload)", kind: "error", reason: String(err) }, ...prev]);
    }
    setBusy(false);
    e.target.value = "";
  }

  async function addDb() {
    if (!dbUrl.trim()) return;
    setDbMsg({ kind: "info", text: "connecting…" });
    const r = await connectDb(dbUrl.trim(), dbName.trim());
    if (r.connected) {
      setDbMsg({ kind: "ok", text: `connected "${r.name}" (${r.dialect}) — ${r.tables.length} table(s)` });
      setDbUrl("");
      setDbName("");
      await refreshSources();
    } else {
      setDbMsg({ kind: "err", text: r.error || "could not connect" });
    }
  }

  return (
    <div className="card">
      <h2>Add your data</h2>
      <p className="muted">
        Upload spreadsheets and documents, or connect a live database. CSVs become
        queryable tables, PDFs/notes become searchable knowledge, and database URLs
        are connected as live sources.
      </p>

      <label className="drop">
        <input type="file" multiple accept=".csv,.pdf,.txt,.md" onChange={handleFiles} />
        {busy ? "Uploading…" : "Choose files — CSV, PDF, TXT, MD (you can pick many)"}
      </label>

      <div className="db-row">
        <input
          className="grow"
          placeholder="Database URL  e.g. postgresql://user:pass@host:5432/dbname"
          value={dbUrl}
          onChange={(e) => setDbUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addDb()}
        />
        <input
          className="name"
          placeholder="label (optional)"
          value={dbName}
          onChange={(e) => setDbName(e.target.value)}
        />
        <button onClick={addDb}>Connect DB</button>
      </div>
      {dbMsg && <div className={"dbmsg " + dbMsg.kind}>{dbMsg.text}</div>}

      {results.length > 0 && (
        <ul className="results">
          {results.map((r, i) => (
            <li key={i}>
              <strong>{r.name}</strong>{" "}
              {r.kind === "dataset" && <span>table <code>{r.table}</code>, {r.rows} rows</span>}
              {r.kind === "document" && <span>document, {r.chars} chars</span>}
              {r.kind === "skipped" && <span className="warn">skipped: {r.reason}</span>}
              {r.kind === "error" && <span className="warn">error: {r.reason}</span>}
            </li>
          ))}
        </ul>
      )}

      <div className="sources">
        <div className="sources-title">Connected sources</div>
        {sources.length === 0 && <div className="muted small">none yet</div>}
        {sources.map((s) => (
          <div key={s.name} className="src">
            <span className="src-name">{s.name}</span>
            <span className="src-dialect">{s.dialect}</span>
            <span className="src-tables">{s.tables.length ? s.tables.join(", ") : "(no tables)"}</span>
          </div>
        ))}
      </div>

      {onContinue && (
        <div className="row end">
          <button className="primary" onClick={onContinue}>
            {continueLabel}
          </button>
        </div>
      )}
      <p className="hint">
        Sample jokes and policy are preloaded — you can skip this and just chat.
      </p>
    </div>
  );
}
