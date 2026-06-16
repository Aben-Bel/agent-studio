from core.declare import skill

@skill("punch_up", "Rewrite the given text to be punchier, in the given style.",
       limits="Restyles wording of supplied text only; adds no facts, data, or analysis.")
def punch_up(text, style=""):
    return f"[{style}] {text.strip()} — now punchier!"
