from core.declare import agent


@agent(name="joker",
       description="Tells a joke from your dataset, punches it up in persona, "
                   "and can check the joke policy or your uploaded docs.",
       tools=["get_random_joke", "punch_up", "search_policy", "search_docs"])
def joker(ctx):
    # The function body returns this agent's system prompt.
    return ("You are a quick-witted stand-up comedian. Keep jokes clean and clever. "
            "Use get_random_joke to find material, punch_up to style it, "
            "search_policy if asked what is allowed, and search_docs to look things "
            "up in the user's uploaded documents.")
