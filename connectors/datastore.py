import os, csv, sqlite3, random
from core.config import cfg


def _conn():
    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    return sqlite3.connect(cfg.db_path)


BUILTIN = [
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "I told my computer I needed a break, and it said no problem, it will go to sleep.",
    "Why don't skeletons fight each other? They don't have the guts.",
]


def load_csv(path, table):
    """Load a CSV upload into a SQL table. A real database link is just a
    different connection string against this same interface."""
    with open(path, encoding="utf-8", errors="ignore") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    header = [c.strip() or f"col{i}" for i, c in enumerate(rows[0])]
    db = _conn()
    cols = ", ".join(f'"{h}" text' for h in header)
    db.execute(f'drop table if exists "{table}"')
    db.execute(f'create table "{table}" ({cols})')
    ph = ", ".join("?" for _ in header)
    db.executemany(f'insert into "{table}" values ({ph})',
                   [r + [""] * (len(header) - len(r)) for r in rows[1:]])
    db.commit()
    n = db.execute(f'select count(*) from "{table}"').fetchone()[0]
    db.close()
    return n


def random_joke():
    """Pull a joke from the uploaded dataset; fall back to builtins."""
    db = _conn()
    try:
        tabs = [r[0] for r in db.execute(
            "select name from sqlite_master where type='table'").fetchall()]
        if "jokes" in tabs:
            rows = db.execute('select * from "jokes"').fetchall()
            cols = [d[0] for d in db.execute('select * from "jokes" limit 1').description]
            if rows:
                row = random.choice(rows)
                d = dict(zip(cols, row))
                setup = d.get("setup") or d.get("question") or ""
                punch = d.get("punchline") or d.get("answer") or ""
                return f"{setup} {punch}".strip() or " | ".join(str(x) for x in row)
    finally:
        db.close()
    return random.choice(BUILTIN)


def run_sql(sql):
    db = _conn()
    try:
        cur = db.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows
    finally:
        db.close()
