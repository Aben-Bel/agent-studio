from typing import Dict, List, Any


ROLE_GROUPS: Dict[str, Dict[str, Any]] = {
    "quality_metrology_defect": {
        "display_name": "Quality, Metrology & Defect Inspection",
        "description": "Focuses on measurement data, defect patterns, inspection results, quality flags, and spec-limit violations.",
        "keywords": ["quality", "metrology", "defect", "inspection", "measurement", "spec", "limit", "wafer map", "quality flag"],
        "role_ids": [
            "quality_metrology_engineer",
            "defect_inspection_engineer",
            "reliability_engineer",
        ],
    },
    "failure_analysis_rca": {
        "display_name": "Failure Analysis & RCA",
        "description": "Focuses on historical root-cause cases, failure labels, defect signatures, known issues, and countermeasures.",
        "keywords": ["failure", "rca", "root cause", "historical", "countermeasure", "failure code", "known issue", "defect signature"],
        "role_ids": [
            "failure_analysis_rca_engineer",
            "product_engineer",
        ],
    },
    "data_automation_systems": {
        "display_name": "Data, Automation & Systems",
        "description": "Focuses on statistical analysis, data quality, schema mapping, MES data, sensor readings, automation events, and control behavior.",
        "keywords": ["data", "automation", "systems", "mes", "statistics", "correlation", "anomaly", "feature", "sensor", "control"],
        "role_ids": [
            "data_scientist_statistical_analyst",
            "mes_data_engineer",
            "automation_controls_engineer",
        ],
    },
}


ROLE_PROFILES: Dict[str, Dict[str, Any]] = {
    "quality_metrology_engineer": {
        "broad_group_id": "quality_metrology_defect",
        "display_name": "Quality / Metrology Engineer",
        "status": "Core",
        "specific_task": "Reviews measurement data, spec limits, inspection results, and abnormal quality flags.",
        "relevance": "Very high: measurement, yield, and quality data are central to explainable RCA.",
        "dataset_fields": ["measurement_value", "spec_limit", "control_limit", "quality_flag", "inspection_result", "wafer_map_summary", "yield_rate"],
        "keywords": ["quality", "metrology", "measurement", "inspection", "spec limit", "control limit", "quality flag"],
    },
    "defect_inspection_engineer": {
        "broad_group_id": "quality_metrology_defect",
        "display_name": "Defect Inspection Engineer",
        "status": "Optional",
        "specific_task": "Looks for defect count/type/location patterns and links them to affected lots or process steps.",
        "relevance": "High if defect data exists; otherwise combine under Quality / Metrology Engineer.",
        "dataset_fields": ["defect_count", "defect_type", "defect_density", "wafer_zone", "inspection_step", "image_label", "yield_rate"],
        "keywords": ["defect", "defect count", "defect type", "defect density", "wafer zone", "inspection"],
    },
    "reliability_engineer": {
        "broad_group_id": "quality_metrology_defect",
        "display_name": "Reliability Engineer",
        "status": "Research-only",
        "specific_task": "Checks long-term reliability/failure indicators after production or stress testing.",
        "relevance": "Low for MVP: relevant only if reliability or post-production failure data exists.",
        "dataset_fields": ["reliability_test_result", "stress_test", "failure_rate", "burn_in_result", "lifetime_metric"],
        "keywords": ["reliability", "stress test", "failure rate", "burn in", "lifetime"],
    },
    "failure_analysis_rca_engineer": {
        "broad_group_id": "failure_analysis_rca",
        "display_name": "Failure Analysis / RCA Engineer",
        "status": "Conditional",
        "specific_task": "Maps symptoms to known failure mechanisms and historical root-cause cases.",
        "relevance": "High only when historical RCA or failure-label data exists; otherwise it may become speculative.",
        "dataset_fields": ["failure_code", "root_cause_label", "defect_signature", "historical_case_id", "countermeasure", "known_issue_flag"],
        "keywords": ["failure analysis", "rca", "root cause", "failure code", "root cause label", "historical case", "countermeasure"],
    },
    "product_engineer": {
        "broad_group_id": "failure_analysis_rca",
        "display_name": "Product Engineer",
        "status": "Optional",
        "specific_task": "Connects yield issues to product/device behavior, test bins, and customer-facing impact.",
        "relevance": "Medium: useful if the dataset includes product IDs, test bins, or product-level yield.",
        "dataset_fields": ["product_id", "device_type", "test_bin", "electrical_test_result", "product_yield", "yield_rate"],
        "keywords": ["product", "device", "test bin", "electrical test", "product yield"],
    },
    "data_scientist_statistical_analyst": {
        "broad_group_id": "data_automation_systems",
        "display_name": "Data Scientist / Statistical Analyst",
        "status": "Core",
        "specific_task": "Runs correlations, anomaly detection, feature importance, grouping, and confidence scoring.",
        "relevance": "Very high: provides the evidence layer that prevents persona outputs from becoming guesses.",
        "dataset_fields": ["all_dataset_columns", "numeric_columns", "categorical_columns", "target_yield", "anomaly_score", "correlation_score"],
        "keywords": ["data scientist", "statistical", "statistics", "correlation", "anomaly", "outlier", "feature importance", "confidence"],
    },
    "mes_data_engineer": {
        "broad_group_id": "data_automation_systems",
        "display_name": "MES / Data Engineer",
        "status": "Research-only",
        "specific_task": "Understands how data is stored, joined, cleaned, and queried from manufacturing systems.",
        "relevance": "Medium: important for real deployment; in hackathon this may be handled by ingestion/backend.",
        "dataset_fields": ["mes_table", "sql_query_output", "lot_history", "event_log", "data_quality_flag", "schema_mapping"],
        "keywords": ["mes", "data engineer", "sql", "database", "schema", "lot history", "event log", "data quality"],
    },
    "automation_controls_engineer": {
        "broad_group_id": "data_automation_systems",
        "display_name": "Automation / Controls Engineer",
        "status": "Optional",
        "specific_task": "Checks sensors, control loops, automation events, and whether controls drifted or failed.",
        "relevance": "Medium if sensor/control data exists; otherwise merge insights into Process or Equipment personas.",
        "dataset_fields": ["sensor_readings", "control_loop_state", "setpoint", "actual_value", "controller_alarm", "yield_rate"],
        "keywords": ["automation", "controls", "sensor", "control loop", "setpoint", "actual value", "controller alarm"],
    },
}


def _score_keywords(text: str, keywords: List[str]) -> int:
    text = text.lower()
    score = 0

    for keyword in keywords:
        if keyword.lower() in text:
            score += 1

    return score


def get_roles_by_group(group_id: str) -> List[Dict[str, Any]]:
    group = ROLE_GROUPS.get(group_id)

    if not group:
        return []

    roles = []

    for role_id in group["role_ids"]:
        role = ROLE_PROFILES[role_id].copy()
        role["role_id"] = role_id
        roles.append(role)

    return roles


def match_role_profile(user_text: str) -> Dict[str, Any]:
    role_scores = {}
    group_scores = {}

    simplified_user_text = user_text.lower().replace("/", " ").replace("-", " ")

    for role_id, role in ROLE_PROFILES.items():
        score = _score_keywords(user_text, role["keywords"])

        role_name = role["display_name"].lower()
        simplified_role_name = role_name.replace("/", " ").replace("-", " ")

        # Strong boost when the exact role name appears
        if role_name in user_text.lower():
            score += 10

        # Strong boost when role name appears without symbols like / or -
        if simplified_role_name in simplified_user_text:
            score += 10

        # Extra direct matching for common role phrases
        if "defect inspection engineer" in simplified_user_text and role_id == "defect_inspection_engineer":
            score += 10

        if "quality metrology engineer" in simplified_user_text and role_id == "quality_metrology_engineer":
            score += 10

        if "failure analysis" in simplified_user_text and role_id == "failure_analysis_rca_engineer":
            score += 10

        if "data scientist" in simplified_user_text and role_id == "data_scientist_statistical_analyst":
            score += 10

        if "automation controls" in simplified_user_text and role_id == "automation_controls_engineer":
            score += 10

        role_scores[role_id] = score

    for group_id, group in ROLE_GROUPS.items():
        group_scores[group_id] = _score_keywords(user_text, group["keywords"])

    best_role_id = max(role_scores, key=role_scores.get)
    best_group_id = max(group_scores, key=group_scores.get)

    best_role_score = role_scores[best_role_id]
    best_group_score = group_scores[best_group_id]

    if best_role_score == 0 and best_group_score == 0:
        fallback_role = ROLE_PROFILES["data_scientist_statistical_analyst"].copy(
        )
        fallback_role["role_id"] = "data_scientist_statistical_analyst"

        return {
            "match_type": "fallback",
            "selected_group": ROLE_GROUPS["data_automation_systems"],
            "selected_group_id": "data_automation_systems",
            "selected_role": fallback_role,
            "candidate_roles": get_roles_by_group("data_automation_systems"),
            "message": "No clear role or group was detected, so the analyzer defaults to Data Scientist / Statistical Analyst.",
        }

    # Prefer specific role when it has equal or higher score.
    # Only choose broad group if the group score is clearly stronger.
    if best_group_score > best_role_score:
        return {
            "match_type": "broad_group",
            "selected_group": ROLE_GROUPS[best_group_id],
            "selected_group_id": best_group_id,
            "selected_role": None,
            "candidate_roles": get_roles_by_group(best_group_id),
            "message": "A broad group was detected. The analyzer should choose one of the candidate roles depending on available dataset columns.",
        }

    selected_role = ROLE_PROFILES[best_role_id].copy()
    selected_role["role_id"] = best_role_id
    group_id = selected_role["broad_group_id"]

    return {
        "match_type": "specific_role",
        "selected_group": ROLE_GROUPS[group_id],
        "selected_group_id": group_id,
        "selected_role": selected_role,
        "candidate_roles": [selected_role],
        "message": "A specific role was detected.",
    }
