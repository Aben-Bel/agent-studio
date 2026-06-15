import os, csv, re, random
from sqlalchemy import (create_engine, inspect, text, event,
                        MetaData, Table, Column, String)
from sqlalchemy.engine import make_url
from core.config import cfg


# A "source" is any SQL database we can talk to. "local" is the bundled SQLite
# file that holds uploaded CSVs; every Postgres/MySQL/... URL the user connects
# becomes another named source. Same interface, different connection string -
# which is the whole point: a CSV table and a live Postgres link are queried
# identically downstream.
_ENGINES: dict = {}

BUILTIN = [
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "I told my computer I needed a break, and it said no problem, it will go to sleep.",
    "Why don't skeletons fight each other? They don't have the guts.",
]


def _safe_name(name, fallback="data"):
    """SQL-safe identifier: lowercase, alnum + underscore, never empty / leading digit."""
    s = re.sub(r"\W+", "_", (name or "").strip().lower()).strip("_")
    if not s or s[0].isdigit():
        s = (fallback + "_" + s).strip("_")
    return s or fallback


def _normalize_url(url):
    """Accept the URLs people actually paste. SQLAlchemy wants 'postgresql://',
    but Heroku/Railway/etc. hand out 'postgres://'."""
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _engine(source="local"):
    if source not in _ENGINES:
        if source == "local":
            os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
            # Team mode runs several agent threads at once, all touching this
            # SQLite file (audit writes + tool reads). WAL + a long busy timeout
            # let concurrent access WAIT for a lock instead of failing with
            # "database is locked" (which otherwise kills the SSE stream).
            eng = create_engine(
                f"sqlite:///{cfg.db_path}",
                connect_args={"timeout": 30, "check_same_thread": False})

            @event.listens_for(eng, "connect")
            def _sqlite_pragmas(dbapi_conn, _rec):   # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.close()

            _ENGINES["local"] = eng
        else:
            raise KeyError(f"unknown data source '{source}'. "
                           f"Connect it first via connect_db().")
    return _ENGINES[source]


def connect_db(url, name=None):
    """Register an external database (Postgres, MySQL, ...) by URL so it becomes
    a queryable source alongside the local CSV store. Validates the connection
    and returns what is inside it. Multiple URLs can be connected at once."""
    url = _normalize_url(url)
    if not url:
        raise ValueError("empty database url")
    try:
        parsed = make_url(url)
    except Exception as e:
        raise ValueError(f"invalid database url: {e}")
    name = _safe_name(name or parsed.database or parsed.host or "db", "db")
    if name == "local":                      # never shadow the bundled store
        name = "local_db"
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as cx:                # fail fast on bad creds / unreachable host
        cx.execute(text("select 1"))
    _ENGINES[name] = eng
    return {"name": name, "dialect": eng.dialect.name,
            "tables": inspect(eng).get_table_names()}


# Platform-internal tables - hidden from /sources so users only see THEIR data.
_INTERNAL_TABLES = {"doc_chunks", "documents", "runs", "run_steps"}


def list_sources():
    """Every connected source and the (user) tables in it (for /sources and tooling)."""
    _engine("local")                         # make sure local is always present
    out = []
    for name, eng in _ENGINES.items():
        try:
            tables = [t for t in inspect(eng).get_table_names() if t not in _INTERNAL_TABLES]
        except Exception:
            tables = []
        out.append({"name": name, "dialect": eng.dialect.name, "tables": tables})
    return out


_LAST_UPLOAD = None   # (source, table) of the most recently uploaded CSV


def load_csv(path, table=None, source="local"):
    """Load a CSV upload into its OWN table on the given source. The table name
    defaults to the file name, so uploading several CSVs no longer clobbers a
    single shared table."""
    global _LAST_UPLOAD
    table = _safe_name(table or os.path.splitext(os.path.basename(path))[0], "dataset")
    with open(path, encoding="utf-8", errors="ignore", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {"table": table, "rows": 0, "source": source}

    # Build de-duplicated, non-empty headers.
    header, seen = [], {}
    for i, c in enumerate(rows[0]):
        h = _safe_name(c, f"col{i}")
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        header.append(h)

    eng = _engine(source)
    md = MetaData()
    tbl = Table(table, md, *[Column(h, String) for h in header])
    data = [r + [""] * (len(header) - len(r)) for r in rows[1:]]
    with eng.begin() as cx:
        tbl.drop(cx, checkfirst=True)
        tbl.create(cx)
        if data:
            cx.execute(tbl.insert(),
                       [dict(zip(header, r[:len(header)])) for r in data])
    _LAST_UPLOAD = (source, table)
    return {"table": table, "rows": len(data), "source": source}


def get_uploaded_file(name=None):
    """Return an uploaded CSV as a file-like object pandas can read (or None).
    Uploaded CSVs are ingested into their own SQL table, so we serialise that table
    back to CSV text on demand - the upload's temp file is long gone by the time a
    tool wants it. With several uploads, pass `name` (a filename or table name) to
    pick one; omit it for the most recently uploaded."""
    import io
    if name:                                 # caller asked for a specific upload
        want = _safe_name(os.path.splitext(name)[0])
        target = next(((s["name"], t) for s in list_sources()
                       for t in s.get("tables", []) if t == want), None)
    else:
        target = _LAST_UPLOAD
        if target is None:                   # nothing uploaded this run -> last table, if any
            tables = [(s["name"], t) for s in list_sources() for t in s.get("tables", [])]
            target = tables[-1] if tables else None
    if target is None:
        return None
    src, tbl = target
    try:
        cols, rows = run_sql(f'SELECT * FROM "{tbl}"', source=src)
    except Exception:
        return None
    buf = io.StringIO()
    w = csv.writer(buf)
    if cols:
        w.writerow(cols)
    w.writerows(rows)
    buf.seek(0)
    return buf


def run_sql(sql, source="local"):
    """Run a query against a source. Returns (columns, rows)."""
    eng = _engine(source)
    with eng.connect() as cx:
        res = cx.execute(text(sql))
        if res.returns_rows:
            cols = list(res.keys())
            rows = [list(r) for r in res.fetchall()]
        else:
            cols, rows = [], []
    return cols, rows


def random_joke():
    """Pull a joke from the local 'jokes' table; fall back to builtins."""
    eng = _engine("local")
    if "jokes" not in inspect(eng).get_table_names():
        return random.choice(BUILTIN)
    md = MetaData()
    jokes = Table("jokes", md, autoload_with=eng)
    with eng.connect() as cx:
        rows = cx.execute(jokes.select()).mappings().all()
    if not rows:
        return random.choice(BUILTIN)
    d = random.choice(rows)
    setup = d.get("setup") or d.get("question") or ""
    punch = d.get("punchline") or d.get("answer") or ""
    return f"{setup} {punch}".strip() or " | ".join(str(v) for v in d.values())
