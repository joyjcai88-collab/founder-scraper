"""Google Custom Search JSON API integration.

Uses Google's Programmable Search Engine (free: 100 queries/day).
Requires GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables.

Setup:
1. Create a Custom Search Engine at https://programmablesearchengine.google.com/
   - Set "Search the entire web" = ON
2. Get an API key at https://console.cloud.google.com/apis/credentials
3. Enable "Custom Search API" in your GCP project
4. Set env vars: GOOGLE_API_KEY, GOOGLE_CSE_ID
"""

from __future__ import annotations

import os
from typing import Dict, List

import httpx

GOOGLE_API_URL = "https://www.googleapis.com/customsearch/v1"


def google_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Search Google via Custom Search JSON API.

    Returns same format as ddg_search: [{title, href, body}].
    Returns empty list if API key is not configured.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        return []

    results: List[Dict[str, str]] = []

    # Google CSE returns max 10 per request
    num = min(max_results, 10)

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                GOOGLE_API_URL,
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": str(num),
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"[google] Search request failed: {exc}", flush=True)
        return results

    items = data.get("items", [])
    for item in items[:max_results]:
        title = item.get("title", "").strip()
        href = item.get("link", "").strip()
        body = item.get("snippet", "").strip()

        if href and title:
            results.append({"title": title, "href": href, "body": body})

    print(f"[google] query={query[:80]!r} → {len(results)} results", flush=True)
    return results


def is_google_configured() -> bool:
    """Check if Google Custom Search API credentials are set."""
    return bool(os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID"))
