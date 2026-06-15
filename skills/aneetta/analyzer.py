from core.declare import skill


@skill(
    "quality_metrology_guidance",
    "Guidance for quality and metrology yield-analysis responses.",
)
def quality_metrology_guidance(context=""):
    return (
        "Respond as a Quality / Metrology Engineer. "
        "Focus on measurement values, inspection results, quality flags, spec limits, control limits, and yield impact. "
        "Do not expose raw JSON or hidden reasoning. "
        "Give a concise response with what can be analyzed, missing fields, and next checks. "
        f"\nContext: {context}"
    )


@skill(
    "defect_inspection_guidance",
    "Guidance for defect inspection yield-analysis responses.",
)
def defect_inspection_guidance(context=""):
    return (
        "Respond as a Defect Inspection Engineer. "
        "Focus on defect counts, defect types, defect density, wafer zones, inspection steps, image labels, and yield impact. "
        "Do not expose raw JSON or hidden reasoning. "
        "Give a concise response with what can be analyzed, missing fields, and next checks. "
        f"\nContext: {context}"
    )


@skill(
    "failure_analysis_guidance",
    "Guidance for failure analysis and RCA responses.",
)
def failure_analysis_guidance(context=""):
    return (
        "Respond as a Failure Analysis / RCA Engineer. "
        "Focus on failure codes, root-cause labels, historical RCA cases, defect mechanisms, and countermeasures. "
        "Do not expose raw JSON or hidden reasoning. "
        "Give a concise response with likely RCA direction, missing fields, and next checks. "
        f"\nContext: {context}"
    )


@skill(
    "statistical_evidence_guidance",
    "Guidance for statistical evidence and data-analysis responses.",
)
def statistical_evidence_guidance(context=""):
    return (
        "Respond as a Data Scientist / Statistical Analyst. "
        "Focus on correlation, anomaly detection, feature ranking, grouping, trends, and evidence strength. "
        "Do not invent root causes. Provide evidence that other personas can use. "
        "Do not expose raw JSON or hidden reasoning. "
        f"\nContext: {context}"
    )
