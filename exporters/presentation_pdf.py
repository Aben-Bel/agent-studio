"""LaTeX (Beamer) presentation compiled to PDF. Needs a LaTeX engine in the
image (texlive); if absent the API falls back to offering the .tex source."""
from core.declare import exporter
from exporters._latex import build_deck, compile_pdf


@exporter("presentation_pdf", "Slide deck (PDF)",
          description="Beamer presentation compiled to PDF: title, conclusion, and a "
                      "reproducible evidence slide per question.",
          extension="pdf", media_type="application/pdf", needs=["pdflatex"])
def presentation_pdf(doc):
    return compile_pdf(build_deck(doc))
