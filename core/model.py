import itertools
from .config import cfg
from .util import retry, log

_ids = itertools.count(1)


class Resp:
    """Neutral model response. tool_calls: list of {id, name, arguments(dict)}."""
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def complete(messages, functions=None, system=""):
    """messages: neutral history. functions: [{name, description, schema}].
    Returns Resp. Mock mode emulates a tool-using model so the whole demo
    runs offline; flip MOCK_LLM=0 with AWS creds to use Bedrock."""
    if cfg.mock_llm:
        return _mock(messages, functions or [], system)
    return _bedrock(messages, functions or [], system)


# ---------------- offline mock (emulates tool use) ----------------
def _called(messages):
    # Only count tools used SINCE the last human message, so each new chat turn
    # can use its tools again (e.g. fetch a FRESH joke) instead of treating an
    # earlier turn's calls as already done.
    turn = messages
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            turn = messages[i:]
            break
    return {m.get("name") for m in turn if m.get("role") == "tool"}


def _last_tool_result(messages):
    for m in reversed(messages):
        if m.get("role") == "tool":
            return m.get("content", "")
    return ""


def _mock(messages, functions, system):
    """Domain-agnostic offline stand-in. It walks the agent's tools once each
    (filling required args best-effort from the user's message), then delivers a
    summary. This lets ANY agent's wiring be demonstrated offline — it is NOT the
    real reasoning agent, just a deterministic emulation of tool use."""
    done = _called(messages)
    user_text = next((m["content"] for m in reversed(messages)
                      if m.get("role") == "user"), "")

    for f in functions:
        n = f["name"]
        if n in done or n == "ask_human":         # ask_human only when explicitly wanted
            continue
        return Resp(tool_calls=[_call(n, _mock_args(f, user_text))])

    used = [m for m in messages if m.get("role") == "tool"]
    if used:
        return Resp(content="Investigation skeleton complete — the steps above show the "
                            "tools and data the RCA agent will use. (Reasoning agent not "
                            "implemented yet; this is the wired skeleton running offline.)")
    return Resp(content="No tools available; nothing to run.")


def _mock_args(spec, user_text):
    """Fill a tool's required args best-effort so the offline walk-through runs."""
    schema = spec.get("schema", {}) or {}
    props = schema.get("properties", {}) or {}
    required = schema.get("required", list(props.keys()))
    args = {}
    for p in required:
        typ = (props.get(p) or {}).get("type", "string")
        args[p] = user_text[:120] if typ == "string" else (0 if typ in ("integer", "number") else "")
    return args


def _call(name, args):
    return {"id": f"c{next(_ids)}", "name": name, "arguments": args}


# ---------------- real Bedrock converse (verify on AWS) ----------------
@retry()
def _bedrock(messages, functions, system):
    import boto3
    client = boto3.client("bedrock-runtime", region_name=cfg.region)
    bm = _to_bedrock_messages(messages)
    kwargs = {"modelId": cfg.model_id, "messages": bm,
              "inferenceConfig": {"maxTokens": 600, "temperature": 0.5}}
    if system:
        kwargs["system"] = [{"text": system}]
    if functions:
        kwargs["toolConfig"] = {"tools": [
            {"toolSpec": {"name": f["name"], "description": f["description"],
                          "inputSchema": {"json": f.get("schema", {"type": "object",
                                                                    "properties": {}})}}}
            for f in functions]}
    out = client.converse(**kwargs)
    content = out["output"]["message"]["content"]
    calls, text = [], None
    for block in content:
        if "toolUse" in block:
            tu = block["toolUse"]
            calls.append({"id": tu["toolUseId"], "name": tu["name"],
                          "arguments": tu.get("input", {})})
        elif "text" in block:
            text = block["text"]
    return Resp(content=text, tool_calls=calls)


def _to_bedrock_messages(messages):
    bm = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            bm.append({"role": "user", "content": [{"text": m["content"]}]})
        elif role == "assistant" and m.get("tool_calls"):
            bm.append({"role": "assistant", "content": [
                {"toolUse": {"toolUseId": c["id"], "name": c["name"],
                             "input": c["arguments"]}} for c in m["tool_calls"]]})
        elif role == "assistant":
            bm.append({"role": "assistant", "content": [{"text": m.get("content", "")}]})
        elif role == "tool":
            block = {"toolResult": {"toolUseId": m["tool_call_id"],
                                    "content": [{"text": m["content"]}]}}
            # Bedrock requires every toolResult for a single assistant turn to
            # live in ONE user message. When the model calls multiple tools at
            # once, append to the existing toolResult turn instead of starting a
            # new one (otherwise Converse 400s: "Expected toolResult blocks...").
            if bm and bm[-1]["role"] == "user" \
                    and all("toolResult" in b for b in bm[-1]["content"]):
                bm[-1]["content"].append(block)
            else:
                bm.append({"role": "user", "content": [block]})
    return bm
