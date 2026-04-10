"""Pure-Python Brave Search via httpx.

Second search engine alongside DuckDuckGo for better coverage.
No API key needed — scrapes Brave's HTML search results.
"""

from __future__ import annotations

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


def brave_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Search Brave and return a list of {title, href, body} dicts.

    Uses Brave Search HTML page — same return format as ddg_search().

    Brave HTML structure per result:
        <div class="snippet ...">
          <a href="URL" class="...">
            <div class="title ...">TITLE</div>
          </a>
          <div class="generic-snippet ...">
            <div class="content ...">BODY TEXT</div>
          </div>
        </div>
    """
    results: List[Dict[str, str]] = []

    url = "https://search.brave.com/search"
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",  # avoid brotli (not always available)
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            resp = client.get(url, headers=headers, params={"q": query})
            if resp.status_code == 429:
                print(f"[brave] Rate limited (429), skipping", flush=True)
                return results
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        print(f"[brave] Search request failed: {exc}", flush=True)
        return results

    # --- Parse result blocks ---
    # Each result is in a <div class="snippet ..."> with data-type="web"
    # We extract: href from <a>, title from <div class="title ...>, body from <div class="content ...>

    # Strategy: find each snippet block, then extract components from within it
    snippet_re = re.compile(
        r'<div\s+class="snippet[^"]*"[^>]*data-type="web"[^>]*>(.*?)</div>\s*</div>\s*</div>\s*</div>',
        re.DOTALL,
    )

    # Simpler approach: extract title links and snippets separately (they appear in order)
    # Title: <a href="URL" ...><div class="title ...">TITLE</div></a>
    title_re = re.compile(
        r'<a\s+href="([^"]+)"[^>]*class="svelte-[^"]*"[^>]*>'
        r'.*?<div\s+class="title[^"]*"[^>]*>(.*?)</div>',
        re.DOTALL,
    )

    # Snippet body: <div class="content ... t-primary ...">TEXT</div>
    body_re = re.compile(
        r'<div\s+class="content[^"]*t-primary[^"]*"[^>]*>(.*?)</div>',
        re.DOTALL,
    )

    titles = title_re.findall(html)
    bodies = body_re.findall(html)

    for i, (raw_href, raw_title) in enumerate(titles):
        if len(results) >= max_results:
            break

        href = _clean_url(raw_href)
        title = _strip_html(raw_title).strip()
        body = _strip_html(bodies[i]).strip() if i < len(bodies) else ""

        # Skip Brave's own pages and empty results
        if not href or not title:
            continue
        if "brave.com" in href:
            continue

        results.append({"title": title, "href": href, "body": body})

    # Fallback: broader regex if the structured one didn't match
    if not results:
        # Look for any <a> tags inside snippet blocks with real URLs
        link_re = re.compile(
            r'class="snippet[^"]*"[^>]*>.*?<a\s+href="(https?://[^"]+)"',
            re.DOTALL,
        )
        all_title_re = re.compile(
            r'class="title[^"]*"[^>]*title="([^"]*)"',
        )
        all_body_re = re.compile(
            r'class="content[^"]*"[^>]*>([^<]+)',
        )

        links = link_re.findall(html)
        all_titles = all_title_re.findall(html)
        all_bodies = all_body_re.findall(html)

        for i in range(min(len(links), max_results)):
            href = _clean_url(links[i])
            title = _strip_html(all_titles[i]).strip() if i < len(all_titles) else ""
            body = _strip_html(all_bodies[i]).strip() if i < len(all_bodies) else ""
            if href and title and "brave.com" not in href:
                results.append({"title": title, "href": href, "body": body})

    print(f"[brave] query={query[:80]!r} → {len(results)} results", flush=True)
    return results


def _clean_url(raw: str) -> str:
    """Clean and validate a URL from Brave search results."""
    if not raw:
        return ""
    # Brave uses direct URLs (no redirect wrappers)
    if raw.startswith("http"):
        return raw
    if raw.startswith("//"):
        return "https:" + raw
    return ""


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
