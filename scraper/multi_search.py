"""Multi-engine search: combines DuckDuckGo and Brave for better coverage.

Runs both search engines **in parallel** per query and merges/deduplicates results.
Engines:
  1. DuckDuckGo HTML (always available, primary)
  2. Brave Search HTML (always available, secondary)

Both engines run concurrently via asyncio.gather(). No API keys needed.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List
from urllib.parse import urlparse

from scraper.ddg import ddg_search
from scraper.brave_search import brave_search


async def multi_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Search with two engines in parallel and merge results.

    Returns deduplicated [{title, href, body}] — same format as ddg_search.
    """
    # Run both engines concurrently
    ddg_task = asyncio.create_task(_safe_search("ddg", ddg_search, query, max_results))
    brave_task = asyncio.create_task(_safe_search("brave", brave_search, query, max_results))

    engine_results = await asyncio.gather(ddg_task, brave_task)

    # Merge and deduplicate
    all_results: List[Dict[str, str]] = []
    seen_urls: set = set()

    for results in engine_results:
        for item in results:
            href = item.get("href", "")
            url_key = _normalize_url(href)
            if url_key and url_key not in seen_urls:
                seen_urls.add(url_key)
                all_results.append(item)

    # Trim to max_results
    return all_results[:max_results]


async def _safe_search(
    name: str, search_fn, query: str, max_results: int
) -> List[Dict[str, str]]:
    """Run a search function with error handling."""
    try:
        return await search_fn(query, max_results=max_results)
    except Exception as exc:
        print(f"[multi] {name} failed: {exc}", flush=True)
        return []


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.rstrip("/").lower()
        return f"{host}{path}"
    except Exception:
        return url.lower().rstrip("/")
