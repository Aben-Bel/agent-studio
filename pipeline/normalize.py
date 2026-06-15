import re
from core.declare import stage


# Example early stage. Runs before `index` because order is lower. Copy this file
# to add your own stage (OCR, translate, classify, redact PII, …) — pick an
# `order` to place it in the chain. Newlines are kept so chunking still works.
@stage("normalize", order=10, description="Collapse stray whitespace before indexing.")
def normalize(doc):
    doc["text"] = re.sub(r"[ \t]+", " ", doc.get("text", "")).strip()
    return doc
