FROM python:3.11-slim
WORKDIR /app

# LaTeX (Beamer) toolchain for the PDF / slide-deck exporters. A minimal TeX Live
# set: base + the recommended bundle (beamer.cls), pgf/tikz (beamer depends on
# it), recommended fonts, and latexmk to drive the compile. Kept lean on purpose.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base texlive-latex-recommended texlive-pictures \
        texlive-fonts-recommended latexmk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# MOCK_LLM defaults to 1 (offline mock, no AWS calls).
# Set MOCK_LLM=0 plus AWS creds in .env to use real Bedrock.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
