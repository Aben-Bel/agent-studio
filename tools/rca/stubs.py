"""RCA tool STUBS - the slots a future agent will use, declared but not yet
implemented. They are fully registered (typed args, owner, version) and show up
in /capabilities, so the skeleton is complete and each can be wired up
independently by its owner. To implement one: replace the body with a real call
to your FDC system / defect database / case history, keeping the signature."""
from pydantic import BaseModel
from core.declare import tool


def _todo(what, **ctx):
    detail = ", ".join(f"{k}={v}" for k, v in ctx.items() if v not in (None, ""))
    return (f"[not implemented yet] {what}"
            + (f" (requested: {detail})" if detail else "")
            + ". Wire this tool to your data source - the contract is in place.")


class FdcArgs(BaseModel):
    lot_id: str
    parameter: str = ""
    tool_id: str = ""


@tool("query_fdc_timeseries",
      "Fetch FDC (fault-detection-and-classification) process-parameter "
      "time-series for a lot / tool / parameter.",
      FdcArgs, owner="equipment-team", tags=["fdc", "timeseries", "stub"])
def query_fdc_timeseries(lot_id, parameter="", tool_id=""):
    return _todo("Would return the FDC trace", lot=lot_id, parameter=parameter, tool=tool_id)


class WaferMapArgs(BaseModel):
    wafer_id: str


@tool("get_wafer_map",
      "Return the spatial defect / bin map for a wafer (defect signature).",
      WaferMapArgs, owner="defect-team", tags=["wafermap", "stub"])
def get_wafer_map(wafer_id):
    return _todo("Would return the wafer defect map", wafer=wafer_id)


class SimilarCasesArgs(BaseModel):
    signature: str       # defect signature / symptom to match historical cases


@tool("find_similar_cases",
      "Find historical RCA cases with a similar defect signature and their "
      "confirmed root cause.",
      SimilarCasesArgs, owner="rca-core", tags=["cases", "stub"])
def find_similar_cases(signature):
    return _todo("Would return similar historical cases + root causes", signature=signature)
