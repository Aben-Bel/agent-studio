import re, json, math
from sqlalchemy import text as sql
from connectors.datastore import _engine

# Tiny vector RAG store, persisted in app.db. Each chunk is embedded into a
# fixed-size cosine-normalized vector (a deterministic hashing bag-of-words, so
# it survives restarts with no model/network). Same add_document/search API as
# before, so every tool keeps working — swap _vec() for Bedrock Titan embeddings
# later without touching anything else.
DIM = 512


def _h(w):                                   # stable hash (Python's hash() is per-process)
    h = 0
    for c in w:
        h = (h * 131 + ord(c)) & 0xFFFFFFFF
    return h


def _stem(w):                                # crude stemmer so refund≈refunds, allow≈allowed
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _vec(s):
    v = [0.0] * DIM
    for w in re.findall(r"\w+", s.lower()):
        v[_h(_stem(w)) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _init():
    with _engine("local").begin() as cx:
        cx.execute(sql("create table if not exists doc_chunks "
                       "(source text, chunk text, vec text)"))


def add_document(text, source):
    _init()
    rows = [{"s": source, "c": p.strip(), "v": json.dumps(_vec(p))}
            for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not rows:
        return
    with _engine("local").begin() as cx:
        cx.execute(sql("delete from doc_chunks where source=:s"), {"s": source})
        cx.execute(sql("insert into doc_chunks(source,chunk,vec) values (:s,:c,:v)"), rows)


def search(query, k=3):
    _init()
    q = _vec(query)
    with _engine("local").connect() as cx:
        rows = cx.execute(sql("select chunk, vec from doc_chunks")).fetchall()
    scored = [(sum(a * b for a, b in zip(q, json.loads(v))), c) for c, v in rows]
    scored.sort(reverse=True)
    return [c for s, c in scored[:k] if s > 0]
