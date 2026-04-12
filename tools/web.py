"""Web search and URL fetch tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="web_search",
    description="Search the internet for current information. Use this for researching companies, market data, news, real estate listings, competitor intelligence, or any question that needs up-to-date information.",
    schema={
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"],
    },
)
def web_search(query: str) -> str:
    import json
    import web_search as ws

    results = ws.search_web(query)
    return json.dumps(results, indent=2) if results else "No results found."


@tool(
    name="fetch_url",
    description="Fetch and read the content of a specific URL. Use this to read articles, company websites, property listings, or any web page.",
    schema={
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch"}
        },
        "required": ["url"],
    },
)
def fetch_url(url: str) -> str:
    import web_search as ws

    return ws.fetch_url(url)
