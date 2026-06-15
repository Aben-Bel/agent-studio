import os
from dataclasses import dataclass


@dataclass
class Config:
    region: str = os.getenv("AWS_REGION", "eu-central-1")
    model_id: str = os.getenv("MODEL_ID", "amazon.nova-micro-v1:0")
    mock_llm: bool = os.getenv("MOCK_LLM", "1") == "1"   # 1 = run offline, no Bedrock
    db_path: str = os.getenv("DB_PATH", "data/app.db")
    max_steps: int = int(os.getenv("MAX_STEPS", "8"))


cfg = Config()
