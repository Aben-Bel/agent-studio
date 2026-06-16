"""Intake / readiness agent.

A normal, auto-discovered, self-describing agent — the orchestrator has NO special
knowledge of it. Its routing metadata tells the LLM router to pick it for a fresh
investigation (or when the data changed) so it runs ALONGSIDE the analysis specialists.
It inventories the data via check_readiness and reports whether the data can support a
real test. It confirms data CORRECTNESS only — it never asks for the true cause or a
known answer, and it never produces a finding. When the data is ready it says so in one
line and explicitly defers to the analysis specialists; it does not block or refuse."""
from core.declare import agent


@agent(
    name="readiness",
    description="Intake check: inventories the visible data and confirms whether it can "
                "support a real statistical test (group column, binary outcome, enough rows, "
                "variance). Runs alongside the analysis specialists, not instead of them.",
    tools=["check_readiness", "list_data_sources", "ask_human"],
    always=True,   # cross-cutting intake — the router keeps it in every run (read by property)
    when_to_use="FIRST in any fresh investigation, or whenever the connected/selected data "
                "changed — route this TOGETHER WITH the relevant analysis specialists so the "
                "data is validated while they work; once a turn has confirmed the data is "
                "ready and unchanged, it can be omitted",
    how_to_use="it calls check_readiness, reports the inventory + verdict, and on a problem "
               "asks the human to fix it (upload data, confirm which column is the outcome); "
               "answers are folded in as run parameters",
    what_to_use_for="data inventory and contract validation (group column, binary 0/1 outcome, "
                    "sufficient n, non-zero variance) at intake",
    what_not_to_use_for="NOT an analysis agent — it computes no findings and tests no "
                        "hypotheses; it never asks for or supplies the true cause/known answer. "
                        "Do NOT route it ALONE for an analysis question — pair it with a specialist",
)
def readiness(ctx):
    return (
        "You are the intake / readiness check for a semiconductor yield RCA. Your only job "
        "is to confirm the data is correct and analyzable — you never produce a finding and "
        "you never block the team.\n\n"
        "1. Call check_readiness to inventory every visible source and check the analysis "
        "contract. Show the user the inventory it returns.\n"
        "2. Act on the verdict:\n"
        "   - empty: ask_human to upload a defect/process dataset (CSV).\n"
        "   - ambiguous: the column roles can't be resolved. ask_human to confirm WHICH column "
        "is the binary defect/yield outcome and WHICH is the categorical process step/group. "
        "Treat the answer as a run parameter for downstream tools.\n"
        "   - insufficient: the data can't support a test (too few rows per group, or the "
        "outcome has no variance). ask_human to upload more or different data.\n"
        "   - ready: state in ONE line that the data is ready (name the table, group column, "
        "and outcome column) and that the analysis specialists should now run the breakdown. "
        "Do NOT refuse, do NOT say 'I cannot produce findings' — simply confirm and defer.\n\n"
        "Scope note: if the request names specific data sources, only check those. If the user "
        "has selected NO data sources, treat the data as empty and ask them to select or upload "
        "one — do not report tables they did not select.\n\n"
        "Hard rule: confirm data correctness ONLY. Never ask the human for the root cause, the "
        "true answer, or which step is to blame — that is the analysis the team produces, not "
        "input you collect."
    )
