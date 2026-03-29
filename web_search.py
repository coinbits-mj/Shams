"""Web search capability for Shams — gives Claude access to live internet research."""

from __future__ import annotations

import logging
import requests
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)


def search_web(query: str, num_results: int = 5) -> list[dict]:
    """Search the web using a free search API. Returns list of {title, url, snippet}."""
    try:
        # Use DuckDuckGo instant answer API (free, no key needed)
        r = requests.get("https://api.duckduckgo.com/", params={
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
        }, timeout=15)
        data = r.json()

        results = []

        # Abstract (direct answer)
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"][:500],
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:num_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:100],
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", "")[:300],
                })

        return results[:num_results]

    except Exception as e:
        logger.error(f"Web search error: {e}")
        return []


def fetch_url(url: str) -> str:
    """Fetch a URL and return text content (first 5000 chars)."""
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Shams/1.0)"
        })
        r.raise_for_status()

        # Try to extract text from HTML
        text = r.text
        # Basic HTML tag stripping
        import re
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:5000]
    except Exception as e:
        logger.error(f"URL fetch error: {e}")
        return f"Error fetching URL: {e}"
