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
    return {m.get("name") for m in messages if m.get("role") == "tool"}


def _last_tool_result(messages):
    for m in reversed(messages):
        if m.get("role") == "tool":
            return m.get("content", "")
    return ""


def _mock(messages, functions, system):
    names = [f["name"] for f in functions]
    done = _called(messages)
    user_text = next((m["content"] for m in reversed(messages)
                      if m.get("role") == "user"), "").lower()
    last = _last_tool_result(messages)

    # 1) if asked about policy/rules, check policy first
    if "search_policy" in names and "search_policy" not in done \
            and any(w in user_text for w in ("policy", "allowed", "rule", "offensive")):
        return Resp(tool_calls=[_call("search_policy", {"query": user_text[:60]})])
    # 2) get a raw joke from the connector
    if "get_random_joke" in names and "get_random_joke" not in done:
        return Resp(tool_calls=[_call("get_random_joke", {})])
    # 3) punch it up with the persona via a skill
    if "punch_up" in names and "punch_up" not in done and last:
        return Resp(tool_calls=[_call("punch_up", {"raw_joke": last, "style": system[:80]})])
    # 4) deliver
    return Resp(content=last or "I am fresh out of jokes for now.")


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
            bm.append({"role": "user", "content": [
                {"toolResult": {"toolUseId": m["tool_call_id"],
                                "content": [{"text": m["content"]}]}}]})
    return bm
