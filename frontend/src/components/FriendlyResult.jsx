import React, { useState } from "react";
import { useI18n } from "../i18n.jsx";

// Render a tool result for NON-TECHNICAL users. Tool results arrive as a string
// that is usually a JSON / Python-dict dump (the ugly raw blob). We parse it and
// lay it out as readable label → value rows, with a "show raw" escape hatch for
// engineers. If it isn't structured (plain text / a table), we show it as-is.

// Humanize a key: defect_count -> "Defect count", user_text -> "User text".
function label(key) {
  const s = String(key).replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Convert a Python-repr dump (single quotes, True/False/None, strings that may
// contain \n, quotes, parentheses) into JSON by TOKENIZING - a char scanner that
// understands quoted strings with escapes. A naive regex breaks the moment a
// string value contains a backslash or newline (e.g. check_readiness' multi-line
// summary), which is exactly why some results still showed raw. This handles them.
function pyReprToJson(s) {
  let out = "";
  let i = 0;
  const n = s.length;
  while (i < n) {
    const c = s[i];
    if (c === '"' || c === "'") {
      // Read a quoted string (either quote style) and re-emit as a JSON string.
      const quote = c;
      i++;
      let str = "";
      while (i < n) {
        const ch = s[i];
        if (ch === "\\") {            // keep escape sequences intact
          str += s[i] + (s[i + 1] ?? "");
          i += 2;
          continue;
        }
        if (ch === quote) { i++; break; }
        str += ch;
        i++;
      }
      // Escape for JSON: backslashes already preserved; quote the JSON-special chars.
      const esc = str
        .replace(/\\(?!["\\/bfnrtu])/g, "\\\\")   // lone backslashes -> escaped
        .replace(/"/g, '\\"')
        .replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t");
      out += '"' + esc + '"';
    } else {
      out += c;
      i++;
    }
  }
  // Python literals -> JSON literals (outside strings, which are now JSON-quoted).
  return out
    .replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false")
    .replace(/\bNone\b/g, "null");
}

// Tolerant parse: real JSON first, then the tokenizing Python-repr converter.
// Returns the object/array, or null when it isn't structured (plain text/table).
function parseStructured(text) {
  const s = (text || "").trim();
  if (!s || (s[0] !== "{" && s[0] !== "[")) return null;
  try { return JSON.parse(s); } catch { /* fall through */ }
  try { return JSON.parse(pyReprToJson(s)); } catch { return null; }
}

const isScalar = (v) => v === null || ["string", "number", "boolean"].includes(typeof v);

function Scalar({ value }) {
  if (value === null || value === "") return <span className="fr-empty">—</span>;
  if (typeof value === "boolean") return <span className={"fr-bool " + (value ? "yes" : "no")}>{value ? "Yes" : "No"}</span>;
  return <span className="fr-val">{String(value)}</span>;
}

// A list of scalars -> chips; a list of objects -> stacked mini-cards.
function ValueList({ items }) {
  if (items.every(isScalar)) {
    return (
      <span className="fr-chips">
        {items.map((v, i) => <span key={i} className="fr-chip">{v === null ? "—" : String(v)}</span>)}
      </span>
    );
  }
  return (
    <div className="fr-sublist">
      {items.map((it, i) => (
        <div key={i} className="fr-subcard">
          {isScalar(it) ? <Scalar value={it} /> : <Rows obj={it} />}
        </div>
      ))}
    </div>
  );
}

function Field({ k, v }) {
  let body;
  if (isScalar(v)) body = <Scalar value={v} />;
  else if (Array.isArray(v)) body = v.length ? <ValueList items={v} /> : <span className="fr-empty">none</span>;
  else body = <div className="fr-nested"><Rows obj={v} /></div>;
  return (
    <div className="fr-row">
      <div className="fr-key">{label(k)}</div>
      <div className="fr-field">{body}</div>
    </div>
  );
}

function Rows({ obj }) {
  if (Array.isArray(obj)) return <ValueList items={obj} />;
  const keys = Object.keys(obj);
  if (!keys.length) return <span className="fr-empty">—</span>;
  return <>{keys.map((k) => <Field key={k} k={k} v={obj[k]} />)}</>;
}

export default function FriendlyResult({ result }) {
  const { t } = useI18n();
  const [raw, setRaw] = useState(false);
  const text = String(result || "");
  const parsed = parseStructured(text);

  if (!parsed) {
    // Not structured (plain text, an ascii table, etc.) - show verbatim.
    return <pre className="ref-result">{text || "(no result captured)"}</pre>;
  }

  return (
    <div className="fr-wrap">
      {raw
        ? <pre className="ref-result">{text}</pre>
        : <div className="fr-card"><Rows obj={parsed} /></div>}
      <button type="button" className="fr-toggle" onClick={() => setRaw((v) => !v)}>
        {raw ? t("showReadable") : t("showRaw")}
      </button>
    </div>
  );
}
