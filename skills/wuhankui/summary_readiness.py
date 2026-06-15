from core.declare import skill


@skill(
    "check_summary_readiness",
    "Check whether the given `analysis_results` are enough to answer the "
    "`question` for the given `user_persona`. Use `available_data` to decide "
    "which extra data sources or skills are still needed before final summary.",
)
def check_summary_readiness(
    question,
    user_persona,
    analysis_results="",
    available_data="",
):
    required = [
        "production data",
        "process parameters",
        "measurement data",
        "equipment logs",
        "quality data",
        "historical rca",
    ]
    evidence = f"{analysis_results}\n{available_data}".lower()
    missing = [item for item in required if item not in evidence]

    if missing:
        return (
            "Summary readiness: NOT READY\n"
            f"User persona: {user_persona}\n"
            f"Question: {question}\n"
            f"Missing data or skills: {', '.join(missing)}\n"
            "Instruction for fetching part: collect the missing items before "
            "final summarization. For root-cause questions, prioritize equipment "
            "logs, historical RCA, quality data, process parameters, and "
            "measurement data."
        )

    return (
        "Summary readiness: READY\n"
        f"User persona: {user_persona}\n"
        f"Question: {question}\n"
        "The current information is enough for a final persona-based summary. "
        "Summarize likely root cause, evidence, uncertainty, and next action."
    )
