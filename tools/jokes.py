from pydantic import BaseModel
from core.declare import tool
from connectors import datastore, memory


class Empty(BaseModel):
    pass


@tool("get_random_joke", "Fetch a raw joke from the uploaded joke dataset.", Empty)
def get_random_joke():
    return datastore.random_joke()


class PolicyArgs(BaseModel):
    query: str


@tool("search_policy", "Look up the joke policy / manual for what is allowed.", PolicyArgs)
def search_policy(query):
    hits = memory.search(query, k=2)
    return " ".join(hits) if hits else "No policy documents loaded yet."
