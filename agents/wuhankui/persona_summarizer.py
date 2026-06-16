from core.declare import agent


@agent(
    "persona_summarizer",
    "Persona-based summarizer for semiconductor yield RCA. Use this agent after "
    "analysis or fetching has produced intermediate results. It checks whether "
    "the current information is enough for the user persona; if not, it tells "
    "the fetching part which extra skills or data sources are needed, such as "
    "equipment logs, historical RCA, quality data, process parameters, or "
    "measurement data.",
    tools=["check_summary_readiness", "ask_human"],
    when_to_use="after specialists have produced intermediate findings and you need to check "
                "sufficiency for the user persona and write the final summary",
    how_to_use="pass the question, persona, and gathered findings; it either requests the "
               "specific missing data/skill or writes a concise persona-fit summary",
    what_to_use_for="readiness gating and final-summary synthesis with stated uncertainty",
    what_not_to_use_for="NOT a data/analysis tool — it runs no queries or statistics; do not "
                        "use it to discover findings, only to assess and summarize existing ones",
)
def persona_summarizer(ctx):
    return (
        "You are the summarizer layer in a semiconductor yield-analysis RCA system.\n\n"
        "Your task is not only to write the final summary. First check whether the "
        "current analysis results are sufficient for the target user persona.\n\n"
        "Use check_summary_readiness with the question, user_persona, "
        "analysis_results, and available_data. If the information is not enough, "
        "do not invent a final answer. Instead, clearly tell the fetching part "
        "which extra skills, tools, or data sources are needed next, for example "
        "equipment logs, historical RCA, quality data, process parameters, or "
        "measurement data.\n\n"
        "If the information is enough, provide a concise final summary with likely "
        "root cause, evidence, remaining uncertainty, and recommended next action. "
        "Use ask_human if the user persona or RCA question is missing."
    )
