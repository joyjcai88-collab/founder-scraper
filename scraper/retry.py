"""Shared retry and rate-limiting utilities for scrapers.

Provides:
- fetch_with_retry(): exponential backoff on 429/999/403
- get_random_ua(): rotate across realistic browser User-Agent strings
- random_delay(): async sleep with jitter to mimic human behavior
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

import httpx

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
]


def get_random_ua() -> str:
    """Return a random realistic browser User-Agent string."""
    return random.choice(_USER_AGENTS)


def get_headers() -> dict:
    """Return realistic browser headers with a random User-Agent."""
    return {
        "User-Agent": get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }


async def random_delay(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """Sleep for a random duration to mimic human behavior."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    max_retries: int = 3,
    retry_on: tuple[int, ...] = (429, 999, 403),
) -> Optional[httpx.Response]:
    """Fetch a URL with exponential backoff on rate-limit responses.

    Returns the response on success (any non-retry status), or None after
    exhausting retries.
    """
    if headers is None:
        headers = get_headers()

    for attempt in range(max_retries):
        try:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code not in retry_on:
                return resp
            # Rate limited — back off
            wait = (2 ** attempt) + random.uniform(0.5, 1.5)
            print(
                f"[retry] {resp.status_code} on {url[:60]}... "
                f"retrying in {wait:.1f}s (attempt {attempt + 1}/{max_retries})",
                flush=True,
            )
            await asyncio.sleep(wait)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            wait = (2 ** attempt) + random.uniform(0.5, 1.5)
            print(
                f"[retry] {type(exc).__name__} on {url[:60]}... "
                f"retrying in {wait:.1f}s (attempt {attempt + 1}/{max_retries})",
                flush=True,
            )
            await asyncio.sleep(wait)
        except Exception as exc:
            print(f"[retry] Unexpected error: {exc}", flush=True)
            return None

    print(f"[retry] Exhausted {max_retries} retries for {url[:60]}", flush=True)
    return None
