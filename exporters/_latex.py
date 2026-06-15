"""Render the professional document model to a Beamer slide deck (LaTeX) and
compile it to PDF. Template-based and deterministic (no model-written LaTeX): every
special character is escaped and every non-ASCII char transliterated/stripped, so
the deck ALWAYS compiles regardless of the authored content."""
import os
import re
import shutil
import subprocess
import tempfile

# Transliterate the common accented/punctuation characters we actually see, then
# drop anything else outside ASCII so pdflatex never chokes on encoding.
_TR = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
       "é": "e", "è": "e", "ê": "e", "ë": "e", "á": "a", "à": "a", "â": "a",
       "í": "i", "ì": "i", "ó": "o", "ò": "o", "ô": "o", "ú": "u", "ù": "u",
       "ñ": "n", "ç": "c", "–": "-", "—": "-", "‘": "'", "’": "'",
       "“": '"', "”": '"', "…": "...", "•": "-", "→": "->", "×": "x", "≈": "~", "°": " deg"}

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}


def _sanitize(s):
    s = "" if s is None else str(s)
    s = "".join(_TR.get(ch, ch) for ch in s)
    return "".join(ch if ord(ch) < 128 else " " for ch in s)


def _esc(s):
    return "".join(_ESC.get(ch, ch) for ch in _sanitize(s))


def _richtext(s):
    """Escape, then render the bit of Markdown the author emits: **bold** and
    `code`. Safe because * and ` are not LaTeX-special (run AFTER escaping)."""
    s = _esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)
    return s


def _oneline(s, n=110):
    s = " ".join(_sanitize(s).split())
    return s if len(s) <= n else s[: n - 1] + "..."


def _table(t):
    cols = t.get("columns", [])
    rows = t.get("rows", [])
    if not cols:
        return ""
    n = len(cols)
    spec = "l" * n
    out = [r"\vspace{4pt}", r"{\footnotesize\begin{tabular}{" + spec + "}", r"\hline"]
    out.append(" & ".join(r"\textbf{" + _esc(c) + "}" for c in cols) + r" \\ \hline")
    for r in rows[:12]:                          # keep slides readable
        cells = list(r) + [""] * (n - len(r))
        out.append(" & ".join(_esc(c) for c in cells[:n]) + r" \\")
    out += [r"\hline", r"\end{tabular}}"]
    return "\n".join(out)


def build_deck(doc):
    """Return the full .tex source for a self-contained, professional Beamer deck."""
    out = []
    A = out.append
    A(r"\documentclass[aspectratio=169,11pt]{beamer}")
    A(r"\usetheme{default}")
    A(r"\setbeamertemplate{navigation symbols}{}")
    A(r"\definecolor{cgigreen}{RGB}{20,160,90}")
    A(r"\definecolor{cgideep}{RGB}{14,124,70}")
    A(r"\setbeamercolor{structure}{fg=cgigreen}")
    A(r"\setbeamercolor{frametitle}{fg=cgideep}")
    A(r"\setbeamercolor{title}{fg=cgideep}")
    A(r"\setbeamerfont{frametitle}{series=\bfseries}")
    A(r"\setbeamertemplate{itemize item}{\color{cgigreen}\textbullet}")
    A(r"\setbeamertemplate{frametitle}{\vskip6pt\insertframetitle\vskip-2pt\hrule height 1.2pt\vskip2pt}")
    A(r"\title{" + _esc(_oneline(doc.get("title", "Report"), 120)) + "}")
    A(r"\subtitle{" + _esc(_oneline(doc.get("subtitle", "Root-Cause Analysis"))) + "}")
    A(r"\date{" + _esc(doc.get("generated", "")) + "}")
    A(r"\begin{document}")
    A(r"\begin{frame}[plain]\titlepage\end{frame}")

    if doc.get("executive_summary"):
        A(r"\begin{frame}[allowframebreaks]{Executive summary}")
        A(r"{\large " + _richtext(doc["executive_summary"]) + "}")
        A(r"\end{frame}")

    for sec in doc.get("sections", []):
        A(r"\begin{frame}[allowframebreaks]{" + _esc(_oneline(sec.get("heading", "Findings"), 95)) + "}")
        bullets = sec.get("bullets") or []
        if bullets:
            A(r"\begin{itemize}")
            for b in bullets:
                A(r"\item " + _richtext(b))
            A(r"\end{itemize}")
        if sec.get("table"):
            A(_table(sec["table"]))
        if not bullets and not sec.get("table"):
            A(r"\textit{(no detail)}")
        A(r"\end{frame}")

    if doc.get("recommendations"):
        A(r"\begin{frame}[allowframebreaks]{Recommendations}")
        A(r"\begin{enumerate}")
        for r in doc["recommendations"]:
            A(r"\item " + _richtext(r))
        A(r"\end{enumerate}")
        A(r"\end{frame}")

    if doc.get("data_sources"):
        A(r"\begin{frame}{Data sources}")
        A(r"\footnotesize Grounded in verified data:")
        A(r"\begin{itemize}")
        for s in doc["data_sources"][:12]:
            A(r"\item \texttt{" + _esc(s) + "}")
        A(r"\end{itemize}")
        A(r"\end{frame}")

    A(r"\end{document}")
    return "\n".join(out)


def engine():
    """The available LaTeX engine, or None. latexmk preferred (handles reruns)."""
    return shutil.which("latexmk") or shutil.which("pdflatex")


def compile_pdf(tex):
    """Compile .tex source to PDF bytes. Raises a clear error if no engine is
    installed so the API can fall back to offering the .tex source."""
    eng = engine()
    if not eng:
        raise RuntimeError("No LaTeX engine (pdflatex/latexmk) is installed. "
                           "Download the .tex source and compile it locally, or "
                           "install texlive in the backend image.")
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "deck.tex"), "w", encoding="utf-8") as f:
            f.write(tex)
        if eng.endswith("latexmk"):
            cmd = [eng, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "deck.tex"]
            passes = 1
        else:
            cmd = [eng, "-interaction=nonstopmode", "-halt-on-error", "deck.tex"]
            passes = 2   # second pass settles allowframebreaks numbering
        proc = None
        for _ in range(passes):
            proc = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=150)
        pdf = os.path.join(d, "deck.pdf")
        if not os.path.exists(pdf):
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:] if proc else ""
            raise RuntimeError("LaTeX compilation failed:\n" + tail)
        with open(pdf, "rb") as f:
            return f.read()
