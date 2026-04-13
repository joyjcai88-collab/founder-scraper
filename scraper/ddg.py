"""Pure-Python DuckDuckGo text search via httpx (async).

Replaces the `ddgs` package which depends on `primp` (a Rust native binary
that fails to install on Vercel's serverless runtime).

Uses DuckDuckGo's HTML endpoint — no API key needed.
"""

from __future__ import annotations

import asyncio
import re
import random
from typing import Dict, List

import httpx

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


async def ddg_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Search DuckDuckGo and return a list of {title, href, body} dicts.

    Uses the DuckDuckGo HTML-only endpoint (html.duckduckgo.com) which
    returns simple HTML — parsed with regex.

    The HTML structure per result:
        <div class="result ...">
          <h2 class="result__title">
            <a rel="nofollow" class="result__a" href="DIRECT_URL">TITLE</a>
          </h2>
          <a class="result__snippet" href="...">BODY SNIPPET</a>
        </div>
    """
    results: List[Dict[str, str]] = []

    url = "https://html.duckduckgo.com/html/"
    data = {"q": query, "b": ""}

    html = None
    for attempt in range(3):
        headers = {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.post(url, headers=headers, data=data)
                # DDG returns 202 or 429 when rate-limited
                if resp.status_code in (202, 429):
                    wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                    print(f"[ddg] Rate limited ({resp.status_code}), retrying in {wait:.1f}s", flush=True)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                html = resp.text
                break
        except Exception as exc:
            print(f"[ddg] Search request failed: {exc}", flush=True)
            return results

    if not html:
        print(f"[ddg] Exhausted retries for query={query[:60]!r}", flush=True)
        return results

    # --- Parse: extract each result__a (title+href) and result__snippet (body) ---
    # These always appear in order within each result block.

    # 1) Find all title links: <a ... class="result__a" href="URL">TITLE</a>
    title_re = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    # 2) Find all snippets: <a class="result__snippet" ...>BODY</a>
    snippet_re = re.compile(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    titles = title_re.findall(html)
    snippets = snippet_re.findall(html)

    for i, (raw_href, raw_title) in enumerate(titles):
        if len(results) >= max_results:
            break

        href = _extract_url(raw_href)
        title = _strip_html(raw_title).strip()
        body = _strip_html(snippets[i]).strip() if i < len(snippets) else ""

        if href and title:
            results.append({"title": title, "href": href, "body": body})

    print(f"[ddg] query={query[:80]!r} → {len(results)} results", flush=True)
    return results


def _extract_url(raw: str) -> str:
    """Extract the actual URL from a DuckDuckGo link.

    DDG HTML endpoint uses direct URLs in href (not redirect wrappers).
    """
    if not raw:
        return ""

    # Check for DDG redirect wrapper: //duckduckgo.com/l/?uddg=ENCODED_URL
    uddg_match = re.search(r'uddg=([^&]+)', raw)
    if uddg_match:
        from urllib.parse import unquote
        return unquote(uddg_match.group(1))

    # Direct URL
    if raw.startswith("http"):
        return raw

    # Protocol-relative
    if raw.startswith("//"):
        return "https:" + raw

    return raw


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#x27;", "'")
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
