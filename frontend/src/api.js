const BASE = "/api";

export async function getCapabilities() {
  const r = await fetch(`${BASE}/capabilities`);
  return r.json();
}

export async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/upload`, { method: "POST", body: fd });
  return r.json();
}

export async function createAgent(agent) {
  const r = await fetch(`${BASE}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(agent),
  });
  return r.json();
}

// Streams orchestrator events. onEvent is called for each {type, data}.
export async function runChat({ agent, message, history }, onEvent) {
  const res = await fetch(`${BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent, message, history }),
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
