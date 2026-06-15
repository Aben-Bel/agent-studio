from typing import List, Dict, Any

from agents.aneetta.role_profiles import match_role_profile


def check_dataset_support(
    user_text: str,
    dataset_columns: List[str],
) -> Dict[str, Any]:
    """
    Checks which analyzer role/group matches the user input and whether
    the dataset has useful columns for that role.

    dataset_columns should be the actual uploaded CSV column names.
    """

    match = match_role_profile(user_text)

    normalized_dataset_columns = {
        column.lower().strip(): column for column in dataset_columns
    }

    candidate_results = []

    for role in match["candidate_roles"]:
        role_fields = role.get("dataset_fields", [])

        found_fields = []
        missing_fields = []

        for field in role_fields:
            field_lower = field.lower().strip()

            if field in ["all_dataset_columns", "numeric_columns", "categorical_columns"]:
                found_fields.append(field)
                continue

            matched_column = None

            for actual_column_lower, actual_column in normalized_dataset_columns.items():
                if field_lower == actual_column_lower or field_lower in actual_column_lower:
                    matched_column = actual_column
                    break

            if matched_column:
                found_fields.append(matched_column)
            else:
                missing_fields.append(field)

        candidate_results.append({
            "role_id": role["role_id"],
            "role_name": role["display_name"],
            "status": role["status"],
            "specific_task": role["specific_task"],
            "relevance": role["relevance"],
            "found_dataset_fields": found_fields,
            "missing_expected_fields": missing_fields,
            "dataset_support_score": len(found_fields),
        })

    candidate_results = sorted(
        candidate_results,
        key=lambda item: item["dataset_support_score"],
        reverse=True,
    )

    return {
        "user_text": user_text,
        "match_type": match["match_type"],
        "selected_group": match["selected_group"]["display_name"],
        "selected_role": (
            match["selected_role"]["display_name"]
            if match["selected_role"]
            else None
        ),
        "message": match["message"],
        "candidate_role_results": candidate_results,
        "recommended_role": candidate_results[0] if candidate_results else None,
    }
