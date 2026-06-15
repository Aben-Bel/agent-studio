import React, { useState } from "react";
import { uploadFile } from "../api.js";

export default function StepUpload({ onNext }) {
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);

  async function handleFiles(e) {
    const files = Array.from(e.target.files);
    setBusy(true);
    for (const f of files) {
      const r = await uploadFile(f);
      setResults((prev) => [...prev, { name: f.name, ...r }]);
    }
    setBusy(false);
  }

  return (
    <div className="card">
      <h2>Add your data</h2>
      <p className="muted">
        Upload a joke dataset (CSV), plus manuals or policy documents (.txt).
        CSVs become a queryable table; documents become searchable knowledge.
      </p>
      <label className="drop">
        <input type="file" multiple accept=".csv,.txt,.md" onChange={handleFiles} />
        {busy ? "Uploading..." : "Choose files (CSV, TXT, MD)"}
      </label>

      <ul className="results">
        {results.map((r, i) => (
          <li key={i}>
            <strong>{r.name}</strong>{" "}
            {r.kind === "dataset" && <span>dataset, {r.rows} rows</span>}
            {r.kind === "document" && <span>document, {r.chars} chars</span>}
            {r.kind === "skipped" && <span className="warn">skipped: {r.reason}</span>}
          </li>
        ))}
      </ul>

      <div className="row end">
        <button className="primary" onClick={onNext}>
          Next: create agent
        </button>
      </div>
      <p className="hint">
        You can skip uploading; sample jokes and policy are preloaded by the
        seed script.
      </p>
    </div>
  );
}
