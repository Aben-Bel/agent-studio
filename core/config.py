import os
from dataclasses import dataclass, field


@dataclass
class Config:
    app_title: str = os.getenv("APP_TITLE", "Yield Analysis - RCA Platform")
    region: str = os.getenv("AWS_REGION", "eu-central-1")
    model_id: str = os.getenv("MODEL_ID", "amazon.nova-micro-v1:0")
    mock_llm: bool = os.getenv("MOCK_LLM", "1") == "1"   # 1 = run offline, no Bedrock
    db_path: str = os.getenv("DB_PATH", "data/app.db")
    # Allowed CORS origins (comma-separated). "*" for dev; lock down in prod.
    cors_origins: list = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()])
    # Optional external database connected at startup (Postgres/MySQL/...).
    # Users can also connect more at runtime via POST /connect-db.
    database_url: str = os.getenv("DATABASE_URL", "")
    # S3 bucket for file uploads (direct browser upload via presigned URLs).
    s3_bucket: str = os.getenv("S3_BUCKET", "")
    max_steps: int = int(os.getenv("MAX_STEPS", "25"))
    # --- Statistical-validity thresholds for the RCA tools (tools/rca/stats_core.py) ---
    # A group is flagged a candidate cause ONLY if BH-adjusted p < alpha AND |lift| >= min_lift.
    stat_alpha: float = float(os.getenv("STAT_ALPHA", "0.05"))
    stat_min_lift: float = float(os.getenv("STAT_MIN_LIFT", "0.03"))      # min practical effect
    stat_min_group_n: int = int(os.getenv("STAT_MIN_GROUP_N", "30"))      # degeneracy guard
    # Confounder check only runs on variable pairs at least this correlated (|pearson r|).
    stat_confounder_corr: float = float(os.getenv("STAT_CONFOUNDER_CORR", "0.6"))
    stat_logistic_ridge: float = float(os.getenv("STAT_LOGISTIC_RIDGE", "1e-6"))


cfg = Config()
