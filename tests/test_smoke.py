from core.discovery import discover
from core import orchestrator

discover()


def test_capabilities_discovered():
    caps = orchestrator.capabilities()
    assert "rca_assistant" in [a["name"] for a in caps["agents"]]
    assert "correlate_params_vs_yield" in [t["name"] for t in caps["tools"]]
    assert "search_fmea" in [t["name"] for t in caps["tools"]]
    assert "index" in [s["name"] for s in caps["stages"]]


def test_investigation_flow_emits_events():
    types = [ev["type"] for ev in orchestrator.run("rca_assistant", "why is yield dropping")]
    assert types[0] == "agent_switch"
    assert "tool_call" in types
    assert types[-1] == "final"
