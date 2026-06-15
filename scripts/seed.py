"""Load the sample data so the demo works before any upload."""
from connectors import datastore, memory

n = datastore.load_csv("data/sources/jokes.csv", "jokes")
print(f"loaded {n} jokes into the SQL store")

for name in ("joke_manual.txt", "joke_policy.txt"):
    with open(f"data/sources/{name}", encoding="utf-8") as f:
        memory.add_document(f.read(), name)
    print(f"indexed {name}")
