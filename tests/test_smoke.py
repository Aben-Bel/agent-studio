from core.discovery import discover
from core import orchestrator

discover()


def test_capabilities_discovered():
    caps = orchestrator.capabilities()
    names = [a["name"] for a in caps["agents"]]
    assert "joker" in names
    assert "get_random_joke" in [t["name"] for t in caps["tools"]]
    assert "punch_up" in [s["name"] for s in caps["skills"]]


def test_joke_flow_emits_events():
    types = [ev["type"] for ev in orchestrator.run("joker", "tell me a joke")]
    assert types[0] == "agent_switch"
    assert "tool_call" in types
    assert types[-1] == "final"
