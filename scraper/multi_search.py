"""Multi-engine search: combines DuckDuckGo, Google, and Brave for better coverage.

Runs two search engines per query and merges/deduplicates results.
Engine priority:
  1. Google Custom Search (if GOOGLE_API_KEY + GOOGLE_CSE_ID are set)
  2. DuckDuckGo HTML (always available)
  3. Brave Search HTML (always available, used as secondary)

Two engines are always used per query for redundancy.
"""

from __future__ import annotations

from typing import Dict, List
from urllib.parse import urlparse

from scraper.ddg import ddg_search
from scraper.brave_search import brave_search
from scraper.google_search import google_search, is_google_configured


def multi_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Search with two engines and merge results.

    Returns deduplicated [{title, href, body}] — same format as ddg_search.
    """
    # Pick engines: Google (if configured) + DDG, otherwise DDG + Brave
    if is_google_configured():
        engines = [
            ("google", google_search),
            ("ddg", ddg_search),
        ]
    else:
        engines = [
            ("ddg", ddg_search),
            ("brave", brave_search),
        ]

    all_results: List[Dict[str, str]] = []
    seen_urls: set = set()

    for engine_name, search_fn in engines:
        try:
            results = search_fn(query, max_results=max_results)
        except Exception as exc:
            print(f"[multi] {engine_name} failed: {exc}", flush=True)
            continue

        for item in results:
            href = item.get("href", "")
            # Deduplicate by normalized URL (strip trailing slashes, www prefix)
            url_key = _normalize_url(href)
            if url_key and url_key not in seen_urls:
                seen_urls.add(url_key)
                all_results.append(item)

    # Trim to max_results
    return all_results[:max_results]


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
