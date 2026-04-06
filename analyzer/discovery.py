"""Discovery engine: find founders by searching LinkedIn via DuckDuckGo.

No API key needed — uses the ddgs package to search for LinkedIn profiles
matching criteria like industry, stage, product, and founding date.
Parses names, companies, and roles from LinkedIn result titles.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from scraper.safety import sanitize_input


async def discover_founders(
    industry: str,
    stage: Optional[str] = None,
    product: Optional[str] = None,
    date_founded: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, str]]:
    """Search LinkedIn via DuckDuckGo for founders matching company criteria.

    Returns a list of dicts: [{"name": "...", "company": "...", "role": "..."}]
    """
    query_parts = ["site:linkedin.com/in", sanitize_input(industry)]
    if stage:
        query_parts.append(sanitize_input(stage))
    if product:
        query_parts.append(sanitize_input(product))
    if date_founded:
        query_parts.append(f"founded {sanitize_input(date_founded)}")
    query_parts.append("founder OR CEO OR co-founder")

    query = " ".join(query_parts)

    try:
        from ddgs import DDGS
        raw_results = list(DDGS().text(query, max_results=limit * 2))
    except Exception:
        try:
            from duckduckgo_search import DDGS
            raw_results = list(DDGS().text(query, max_results=limit * 2))
        except Exception:
            return []

    results: List[Dict[str, str]] = []
    seen: set = set()

    for item in raw_results:
        href = item.get("href", "")
        title = item.get("title", "")

        # Only process LinkedIn profile URLs
        if "linkedin.com/in/" not in href:
            continue

        # Extract slug to deduplicate
        slug_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', href)
        if not slug_match:
            continue
        slug = slug_match.group(1)
        if slug in seen or slug in ("login", "signup", "feed"):
            continue
        seen.add(slug)

        # Parse title: "Name - Role | LinkedIn" or "Name - Role - Company | LinkedIn"
        parsed = _parse_linkedin_title(title)
        if not parsed["name"]:
            continue

        results.append(parsed)
        if len(results) >= limit:
            break

    return results


def _parse_linkedin_title(title: str) -> Dict[str, str]:
    """Parse a LinkedIn search result title into name, role, company."""
    # Remove " | LinkedIn" or " - LinkedIn" suffix
    title = re.sub(r'\s*[\|·\-]\s*LinkedIn\s*$', '', title, flags=re.IGNORECASE).strip()

    # Remove "..." truncation markers
    title = re.sub(r'\s*\.{3,}\s*', ' ', title).strip()

    name = ""
    role = ""
    company = ""

    # Split by " - " delimiter
    parts = [p.strip() for p in title.split(' - ') if p.strip()]

    if len(parts) >= 3:
        name = parts[0]
        role = parts[1]
        company = parts[2]
    elif len(parts) == 2:
        name = parts[0]
        second = parts[1]
        # Check for "Role at Company" or "Role | Company"
        at_match = re.match(r'(.+?)\s+(?:at|@)\s+(.+)', second, re.IGNORECASE)
        pipe_match = re.match(r'(.+?)\s*\|\s*(.+)', second)
        if at_match:
            role = at_match.group(1).strip()
            company = at_match.group(2).strip()
        elif pipe_match:
            role = pipe_match.group(1).strip()
            company = pipe_match.group(2).strip()
        else:
            role = second
    elif len(parts) == 1:
        name = parts[0]

    # Clean up: remove extra whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    role = re.sub(r'\s+', ' ', role).strip()
    company = re.sub(r'\s+', ' ', company).strip()

    return {
        "name": name,
        "company": company,
        "role": role or "Founder",
    }
