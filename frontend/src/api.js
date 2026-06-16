const BASE = "/api";

export async function getCapabilities() {
  const r = await fetch(`${BASE}/capabilities`);
  return r.json();
}

// Upload one or many files in a single request. Returns { results: [...] }.
export async function uploadFiles(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await fetch(`${BASE}/upload`, { method: "POST", body: fd });
  return r.json();
}

// Backward-compatible single-file upload (kept for callers that still use it).
export async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/upload`, { method: "POST", body: fd });
  return r.json();
}

// Connect an external database (e.g. Postgres) by URL.
export async function connectDb(url, name) {
  const r = await fetch(`${BASE}/connect-db`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, name: name || null }),
  });
  return r.json();
}

// List every connected data source (local CSV store + connected databases).
export async function getSources() {
  const r = await fetch(`${BASE}/sources`);
  return r.json();
}

// Ingestion pipeline status (pending vs done documents + stages).
export async function getProcessStatus() {
  const r = await fetch(`${BASE}/process/status`);
  return r.json();
}

// Preview rows of a table in a connected source (for the inspect modal).
export async function previewTable(source, table, limit = 50) {
  const r = await fetch(`${BASE}/sources/${encodeURIComponent(source)}/${encodeURIComponent(table)}/preview?limit=${limit}`);
  return r.json();
}

// Uploaded documents (PDFs/manuals) and their full text (for inspect).
export async function getDocuments() {
  const r = await fetch(`${BASE}/documents`);
  return r.json();
}
export async function previewDocument(source) {
  const r = await fetch(`${BASE}/documents/${encodeURIComponent(source)}/preview`);
  return r.json();
}

// The investigation audit trail (every run).
export async function getRuns() {
  const r = await fetch(`${BASE}/runs`);
  return r.json();
}

// Suggested starter questions (data-aware) for the empty state.
export async function getSuggestions(lang) {
  const q = lang ? `?lang=${encodeURIComponent(lang)}` : "";
  const r = await fetch(`${BASE}/suggest${q}`);
  return r.json();
}

// Output formats available for download (Markdown, LaTeX, PDF deck, ...).
export async function getExportFormats() {
  const r = await fetch(`${BASE}/export/formats`);
  return r.json();
}

// Generate an artifact for a chat and download it. Abortable via `signal`
// (Stop) and safely re-runnable (Retry); never touches the chat session.
// On success triggers a browser download and returns { filename }.
// On failure throws Error(message) parsed from the JSON error body.
export async function exportReport(chatId, format, signal, title, lang) {
  const res = await fetch(`${BASE}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, format, title: title || null, lang: lang || "en" }),
    signal,
  });
  const media = res.headers.get("Content-Type") || "";
  const buf = await res.arrayBuffer();
  if (!res.ok || media.includes("application/json") || media.includes("text/html")) {
    // Server returned an error (or an SPA/HTML page) - never save that as a file.
    let msg = `export failed (${res.status})`;
    try { msg = JSON.parse(new TextDecoder().decode(buf)).error || msg; } catch { /* */ }
    throw new Error(msg);
  }
  if (buf.byteLength === 0) throw new Error("export produced an empty file");

  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const filename = res.headers.get("X-Filename") || (m && m[1]) || `report.${format}`;
  // Build a correctly-typed Blob from the raw bytes so every browser treats it
  // as the right file type, then download via a temporary anchor.
  const blob = new Blob([buf], { type: media || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.rel = "noopener";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return { filename };
}

// Full persisted trace of one investigation.
export async function getRun(chatId) {
  const r = await fetch(`${BASE}/runs/${encodeURIComponent(chatId)}`);
  return r.json();
}

// Restore a chat session (transcript, status, pending question).
export async function getSession(chatId) {
  const r = await fetch(`${BASE}/sessions/${encodeURIComponent(chatId)}`);
  return r.json();
}

// Add context to a chat while it runs; the orchestrator catches up on its next step.
export async function addContext(chatId, text) {
  const r = await fetch(`${BASE}/sessions/${encodeURIComponent(chatId)}/context`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return r.json();
}

// --- Direct-to-S3 upload (file bytes never pass through the backend) ---
// 1) ask the backend for a presigned URL, 2) PUT the file straight to S3,
// 3) return {key, get_url, ...} so you can hand the key back to the backend.
export async function uploadToS3(file) {
  const presign = await fetch(`${BASE}/uploads/presign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, content_type: file.type || null }),
  }).then((r) => r.json());

  const put = await fetch(presign.upload_url, {
    method: "PUT",
    headers: file.type ? { "Content-Type": file.type } : {},
    body: file,
  });
  if (!put.ok) throw new Error(`S3 upload failed: ${put.status}`);

  return presign; // { key, upload_url, get_url, bucket }
}

// Tell the backend to pick up an uploaded object (by key or link) and ingest it.
export async function ingestFromS3(key) {
  const r = await fetch(`${BASE}/ingest-s3`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  return r.json();
}

// Convenience: upload straight to S3, then ingest in one call.
export async function uploadAndIngest(file) {
  const { key } = await uploadToS3(file);
  return ingestFromS3(key);
}

export async function createAgent(agent) {
  const r = await fetch(`${BASE}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(agent),
  });
  return r.json();
}

// Streams orchestrator events. Pass chat_id to keep a stateful, resumable
// session (memory + human-in-the-loop). onEvent is called for each {type, data}.
export async function runChat({ agent, message, history, chat_id, agents, allow_tools, sources, lang }, onEvent, signal) {
  const res = await fetch(`${BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent, message, history: history || [], chat_id, agents, allow_tools, sources, lang }),
    signal,
  });
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (line) onEvent(JSON.parse(line.slice(5).trim()));
    }
  }
}
