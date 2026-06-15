"""Output plane: turn an investigation into a downloadable artifact.

Symmetric to the input/agent/tool registries - every output FORMAT is a
self-declaring file in exporters/. This module just lists them and runs one
against the structured report built from the audit trail."""
import re
import shutil

from .registry import EXPORTERS
from .document import build_document


def _available(decl):
    return all(shutil.which(b) for b in (decl.needs or []))


def list_formats():
    """Every output format, with whether its external dependency is present."""
    out = []
    for d in EXPORTERS.all().values():
        out.append({"name": d.name, "label": d.label, "description": d.description,
                    "extension": d.extension, "available": _available(d),
                    "needs": d.needs})
    # Stable, friendly order: available first, then by label.
    return sorted(out, key=lambda x: (not x["available"], x["label"]))


def _slug(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "report").lower()).strip("-")
    return s[:40] or "report"


def generate(chat_id, fmt, title=None):
    """Run one exporter. Returns (bytes, filename, media_type). Raises on unknown
    format, missing dependency, empty investigation, or exporter failure - the
    router maps those to clean JSON errors so the chat is never affected."""
    if fmt not in EXPORTERS.all():
        raise KeyError(f"unknown export format '{fmt}'")
    decl = EXPORTERS.get(fmt)
    if not _available(decl):
        raise RuntimeError(f"'{decl.label}' needs {', '.join(decl.needs)} which is "
                           "not installed in this environment.")
    doc = build_document(chat_id, title=title)
    if doc.get("empty"):
        raise ValueError("Nothing to export yet - run an investigation in this chat first.")
    data = decl.fn(doc)
    if isinstance(data, str):
        data = data.encode("utf-8")
    name = f"{_slug(doc['title'])}-{chat_id[:8]}.{decl.extension}"
    return data, name, decl.media_type
