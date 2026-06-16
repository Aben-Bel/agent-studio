"""Pre-generate the German translations for the capability catalog.

The tool/skill/agent descriptions and `limits` are STATIC text. Rather than
translate them live on every backend boot (slow, and an imperative description can
get *obeyed* instead of translated), we translate each ONCE here and commit the
result to core/caps_i18n_de.json. `orchestrator.capabilities()` then serves the
{en, de} pairs with zero model calls.

Run it whenever you add or edit a tool/skill/agent description or its `limits`:

    MOCK_LLM=0 python -m scripts.gen_caps_i18n        # needs AWS creds (real Bedrock)

It is incremental: existing translations are reused; only new/changed English
strings are sent to the model. Review the JSON diff before committing.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.discovery import discover            # noqa: E402
from core.registry import AGENTS, TOOLS, SKILLS, MCP, STAGES   # noqa: E402
from core import model                          # noqa: E402
from core.config import cfg                     # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "core", "caps_i18n_de.json")


def _english_strings():
    """Every distinct English capability string that needs a German pair."""
    discover()
    out = set()
    for a in AGENTS.all().values():
        out.add(a.description)
    for t in TOOLS.all().values():
        out.add(t.description)
        out.add(getattr(t, "limits", ""))
    for s in SKILLS.all().values():
        out.add(s.description)
        out.add(getattr(s, "limits", ""))
    for m in MCP.all().values():
        out.add(m.description)
    for s in STAGES.all().values():
        out.add(s.description)
    return sorted(x for x in out if (x or "").strip())


def main():
    if cfg.mock_llm:
        print("MOCK_LLM is on - translate() is a no-op. Set MOCK_LLM=0 with AWS creds "
              "to generate real German. Aborting so we don't write English-as-German.")
        return 1

    existing = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)

    strings = _english_strings()
    result = {}
    new, reused = 0, 0
    for i, en in enumerate(strings, 1):
        if en in existing and existing[en] and existing[en] != en:
            result[en] = existing[en]
            reused += 1
            continue
        de = model.translate(en, "de")
        result[en] = de
        new += 1
        print(f"[{i}/{len(strings)}] translated: {en[:60]}...")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"\nWrote {len(result)} pairs to {OUT}  (new: {new}, reused: {reused})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
