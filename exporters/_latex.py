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


def _strip_md(s):
    """Remove Markdown decoration so it never survives into a TITLE (where it is
    escaped literally, not rendered). Fixes raw '**' / '`' leaking and the stray
    trailing letter when truncation cuts a '**bold**' span mid-way."""
    s = "" if s is None else str(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.replace("**", "").replace("`", "").replace("*", "")


def _oneline(s, n=110):
    s = " ".join(_strip_md(_sanitize(s)).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "..."


def _title_line(s, n=70):
    """A frame/title is a LABEL, not a sentence: strip markdown, take the first
    clause (before a period), and clamp short. Stops authored prose like 'To
    answer this question, I need the actual data...' from becoming a heading."""
    s = " ".join(_strip_md(_sanitize(s)).split())
    s = re.split(r"(?<=[a-z0-9])\.\s", s, maxsplit=1)[0]   # first sentence only
    s = s.rstrip(" .:-")
    return s if len(s) <= n else s[: n - 1].rstrip() + "..."


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
    L = doc.get("labels") or {}
    A(r"\documentclass[aspectratio=169,12pt]{beamer}")
    # Modern, flat, sans-serif look (Metropolis-inspired) without external themes,
    # so it compiles anywhere: clean typography, generous whitespace, no shadows.
    A(r"\usetheme{default}")
    A(r"\usefonttheme{professionalfonts}")
    A(r"\usepackage[scaled=1.02]{helvet}\renewcommand{\familydefault}{\sfdefault}")
    # sansmath is nice-to-have; never let a missing package break the compile.
    A(r"\IfFileExists{sansmath.sty}{\usepackage{sansmath}\sansmath}{}")
    A(r"\setbeamertemplate{navigation symbols}{}")
    A(r"\setbeamertemplate{itemize/enumerate body begin}{\normalsize}")
    A(r"\definecolor{cgigreen}{RGB}{20,160,90}")
    A(r"\definecolor{cgideep}{RGB}{14,110,64}")
    A(r"\definecolor{inkdark}{RGB}{28,33,40}")
    A(r"\definecolor{inkmute}{RGB}{110,120,130}")
    A(r"\setbeamercolor{normal text}{fg=inkdark}")
    A(r"\setbeamercolor{structure}{fg=cgigreen}")
    A(r"\setbeamercolor{frametitle}{fg=cgideep}")
    A(r"\setbeamercolor{title}{fg=cgideep}")
    A(r"\setbeamercolor{subtitle}{fg=inkmute}")
    A(r"\setbeamerfont{frametitle}{series=\bfseries,size=\Large}")
    A(r"\setbeamerfont{title}{series=\bfseries,size=\huge}")
    A(r"\setbeamerfont{itemize/enumerate body}{size=\normalsize}")
    # generous list spacing so slides breathe instead of becoming text walls
    A(r"\setlength{\leftmargini}{1.6em}")
    A(r"\setbeamertemplate{itemize item}{\color{cgigreen}\raisebox{0.12ex}{\footnotesize$\blacksquare$}}")
    A(r"\setbeamertemplate{itemize subitem}{\color{cgigreen}\textendash}")
    A(r"\setbeamertemplate{frametitle}{\vskip10pt\insertframetitle\vskip3pt"
      r"{\color{cgigreen}\hrule height 2pt}\vskip4pt}")
    # a touch of breathing room on every itemize (etoolbox is standard in texlive)
    A(r"\IfFileExists{etoolbox.sty}{\usepackage{etoolbox}"
      r"\BeforeBeginEnvironment{itemize}{\vskip2pt}}{}")
    A(r"\title{" + _esc(_title_line(doc.get("title", "Report"), 80)) + "}")
    A(r"\subtitle{\normalsize " + _esc(_oneline(doc.get("subtitle", "Root-Cause Analysis"), 95)) + "}")
    A(r"\date{\small " + _esc(doc.get("generated", "")) + "}")
    A(r"\begin{document}")
    A(r"\begin{frame}[plain]\titlepage\end{frame}")

    if doc.get("executive_summary"):
        A(r"\begin{frame}{" + _esc(L.get("summary", "Executive summary")) + "}")
        A(r"\vfill")
        A(r"{\large " + _richtext(_oneline(doc["executive_summary"], 420)) + "}")
        A(r"\vfill")
        A(r"\end{frame}")

    for sec in doc.get("sections", []):
        A(r"\begin{frame}[allowframebreaks]{" + _esc(_title_line(sec.get("heading", "Findings"), 64)) + "}")
        bullets = sec.get("bullets") or []
        if bullets:
            A(r"\begin{itemize}")
            for b in bullets[:6]:                    # cap: one idea per slide, not a wall
                A(r"\item " + _richtext(_oneline(b, 160)))
            A(r"\end{itemize}")
        if sec.get("table"):
            A(_table(sec["table"]))
        if not bullets and not sec.get("table"):
            A(r"\textit{(no detail)}")
        A(r"\end{frame}")

    if doc.get("recommendations"):
        A(r"\begin{frame}[allowframebreaks]{" + _esc(L.get("recommendations", "Recommendations")) + "}")
        A(r"\begin{enumerate}")
        for r in doc["recommendations"][:6]:
            A(r"\item " + _richtext(_oneline(r, 160)))
        A(r"\end{enumerate}")
        A(r"\end{frame}")

    if doc.get("data_sources"):
        A(r"\begin{frame}{" + _esc(L.get("data_sources", "Data sources")) + "}")
        A(r"{\color{inkmute}\footnotesize " + _esc(L.get("grounded", "Grounded in verified data:")) + "}")
        A(r"\begin{itemize}")
        for s in doc["data_sources"][:12]:
            A(r"\item \texttt{\small " + _esc(s) + "}")
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
