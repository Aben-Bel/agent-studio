from core.declare import skill
from core.config import cfg
from core import model


@skill("punch_up", "Rewrite a raw joke in the agent's persona/style.")
def punch_up(raw_joke, style=""):
    if cfg.mock_llm:
        tag = style.split(".")[0][:48] if style else "Comedian"
        return f"{raw_joke} ... (delivered as: {tag})"
    r = model.complete(
        messages=[{"role": "user",
                   "content": f"Rewrite this joke in the style described.\n"
                              f"Style: {style}\nJoke: {raw_joke}\n"
                              f"Return only the rewritten joke."}],
        system="You are a punch-up writer for comedians.")
    return r.content or raw_joke
