"""Demonstrates that tools work from SUBFOLDERS, not just the top level.

This file lives at tools/examples/echo.py and is still auto-discovered, because
discovery recurses into subfolders. Each contributor can keep their own subfolder
(tools/<you>/...) and never touch anyone else's file.
"""
from pydantic import BaseModel
from core.declare import tool


class EchoArgs(BaseModel):
    text: str


@tool("echo", "Echo back the given text (subfolder discovery demo).", EchoArgs)
def echo(text):
    return text
