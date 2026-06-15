"""Output tool: let an agent GENERATE a downloadable artifact (PDF slide deck,
report, LaTeX source) of the investigation when the user asks to download/export/
save the findings. The orchestrator intercepts this by name (it knows the chat
session); it emits a download button into the chat and confirms to the agent.
The body never runs in normal flow."""
from typing import Optional
from pydantic import BaseModel
from core.declare import tool


class DownloadArgs(BaseModel):
    format: str = "presentation_pdf"   # presentation_pdf | report_md | presentation_tex (aliases ok: pdf, slides, report, latex)
    title: Optional[str] = None         # optional report/deck title


@tool("prepare_download",
      "Generate a downloadable file of the findings and show the user a download "
      "button. Use whenever the user asks to download, export, save, or get a PDF / "
      "slide deck / report / document. format: 'presentation_pdf' (slide deck PDF), "
      "'report_md' (written report), or 'presentation_tex' (LaTeX source). You CAN "
      "produce files - never say you cannot.",
      DownloadArgs, owner="output", tags=["output", "download"])
def prepare_download(format="presentation_pdf", title=None):
    return f"(preparing {format} download)"   # intercepted by the orchestrator
