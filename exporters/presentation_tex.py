"""LaTeX (Beamer) presentation source. Always available; the user gets a fully
reproducible .tex they can recompile themselves."""
from core.declare import exporter
from exporters._latex import build_deck


@exporter("presentation_tex", "Slide deck (LaTeX source)",
          description="Beamer presentation as .tex source - reproducible; recompile "
                      "with pdflatex to regenerate the exact PDF.",
          extension="tex", media_type="application/x-tex")
def presentation_tex(doc):
    return build_deck(doc).encode("utf-8")
