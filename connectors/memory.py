import re

# Offline RAG: keyword scoring over chunks. No embeddings so it runs with zero
# network. Swap this one module for a vector store on AWS without touching tools.
_CHUNKS: list[dict] = []


def add_document(text, source):
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para:
            _CHUNKS.append({"source": source, "text": para})


def search(query, k=3):
    terms = set(re.findall(r"\w+", query.lower()))
    scored = []
    for c in _CHUNKS:
        words = set(re.findall(r"\w+", c["text"].lower()))
        score = len(terms & words)
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [c["text"] for _, c in scored[:k]]
