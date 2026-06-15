from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from core.declare import tool
from agents.aneetta.analyzer import check_dataset_support


class RoleSupportArgs(BaseModel):
    user_text: str
    dataset_columns: List[str]
    dataset_id: Optional[str] = None


@tool(
    "aneetta_role_support",
    "Match a semiconductor user role or broad group to analyzer personas and check whether dataset columns support that role.",
    RoleSupportArgs,
)
def aneetta_role_support(
    user_text: str,
    dataset_columns: List[str],
    dataset_id: Optional[str] = None,
) -> Dict[str, Any]:
    result = check_dataset_support(
        user_text=user_text,
        dataset_columns=dataset_columns,
    )
    result["dataset_id"] = dataset_id
    return result
