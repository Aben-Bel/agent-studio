"""Output plane: list output formats and download a generated artifact.

Symmetric to the data plane (inputs) and capabilities (agents/tools): outputs are
self-declaring exporter files, surfaced here. Generation is a normal request the
client can abort (Stop) or re-issue (Retry) without touching the chat session."""
import io
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from core import export
from core.schemas import ExportRequest

router = APIRouter()


@router.get("/export/formats")
def export_formats():
    """Available output formats (Download menu). `available=false` means the format
    needs a binary that is not installed (e.g. LaTeX) - the UI can still offer the
    source-only variants."""
    return {"formats": export.list_formats()}


def _build(chat_id, fmt, title):
    """Shared by POST and GET: generate -> file response, or a clean JSON error."""
    try:
        data, filename, media = export.generate(chat_id, fmt, title)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:  # exporter blew up - surface it, don't 500 silently
        return JSONResponse({"error": f"export failed: {e}"}, status_code=500)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"',
               "Content-Length": str(len(data)),
               "X-Filename": filename}
    return StreamingResponse(io.BytesIO(data), media_type=media, headers=headers)


@router.post("/export")
def run_export(req: ExportRequest):
    """Generate one artifact and stream it as a file download. Errors come back as
    JSON (never a broken download), so the UI shows a message and the chat is
    unaffected."""
    return _build(req.chat_id, req.format, req.title)


@router.get("/export")
def run_export_get(chat_id: str, format: str = "report_md", title: Optional[str] = None):
    """Same as POST, as a plain link - so an in-chat 'Download' can be a normal URL."""
    return _build(chat_id, format, title)
