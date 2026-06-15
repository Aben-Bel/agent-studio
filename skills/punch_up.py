from core.declare import skill

@skill("punch_up", "Rewrite the given text to be punchier, in the given style.")
def punch_up(text, style=""):
    return f"[{style}] {text.strip()} — now punchier!"
