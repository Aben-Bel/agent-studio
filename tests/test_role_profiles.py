from agents.aneetta.analyzer import check_dataset_support

dataset_columns = [
    "lot_id",
    "wafer_id",
    "yield_rate",
    "defect_count",
    "inspection_result",
    "measurement_value",
    "quality_flag",
    "root_cause_label",
    "failure_code",
    "sensor_readings",
    "setpoint",
    "actual_value",
]


examples = [
    "I am from Quality, Metrology and Defect Inspection. Why did yield drop?",
    "I am a Defect Inspection Engineer and I want to check defect patterns.",
    "I am doing RCA and I have historical failure codes.",
    "Run statistical correlation and anomaly detection on this dataset.",
    "I am from automation controls and want to check sensor drift.",
]


for example in examples:
    result = check_dataset_support(example, dataset_columns)

    print("\n---")
    print("Input:", example)
    print("Match type:", result["match_type"])
    print("Selected group:", result["selected_group"])
    print("Selected role:", result["selected_role"])
    print("Recommended role:", result["recommended_role"]["role_name"])
    print("Found fields:", result["recommended_role"]["found_dataset_fields"])
    print("Missing fields:",
          result["recommended_role"]["missing_expected_fields"])
