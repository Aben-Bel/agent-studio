"""Example MCP server declaration.

Drop a file like this in mcp/ (or any subfolder of it) and it self-registers and
shows up in /capabilities — the same drop-a-file pattern as tools/skills/agents.
This is a declaration slot: it records HOW to reach an MCP server. Wiring a live
MCP client to it is a separate step; the registry makes the server discoverable.
"""
from core.declare import mcp


@mcp("filesystem",
     "Read/write files under a sandboxed directory via the reference MCP server.",
     transport="stdio",
     command="npx",
     args=["-y", "@modelcontextprotocol/server-filesystem", "./data"])
def filesystem():
    pass
