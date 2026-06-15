"""Load the sample data so the demo works before any upload."""
import os
from connectors import datastore, memory

# Sample files live in data/sources (preferred) or sources/ — use whichever exists.
SEARCH_DIRS = ["data/sources", "sources"]


def _find(name):
    for d in SEARCH_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


jokes_csv = _find("jokes.csv")
if jokes_csv:
    info = datastore.load_csv(jokes_csv, "jokes")
    print(f"loaded {info['rows']} jokes into the '{info['table']}' table")
else:
    print("no jokes.csv found; the joke tool will fall back to built-ins")

for name in ("joke_manual.txt", "joke_policy.txt"):
    path = _find(name)
    if not path:
        print(f"skipped {name} (not found)")
        continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        memory.add_document(f.read(), name)
    print(f"indexed {name}")
