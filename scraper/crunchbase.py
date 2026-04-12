"""Crunchbase scraper — three-layer extraction strategy.

Layer 1: __NEXT_DATA__ JSON (primary) — Crunchbase is a Next.js app that embeds
         full page data in a <script id="__NEXT_DATA__"> tag as JSON.
Layer 2: Autocomplete API (discovery) — JSON endpoint for finding person slugs.
Layer 3: DuckDuckGo snippet fallback — parse funding info from search snippets.

No API key needed. All layers are free.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from models.founder import CrunchbaseData
from scraper.retry import fetch_with_retry, get_headers, random_delay
from scraper.safety import clean_scraped_text, is_safe_url, sanitize_input

TIMEOUT = 20
CRUNCHBASE_BASE = "https://www.crunchbase.com"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def scrape_crunchbase(name: str, company: str | None = None) -> CrunchbaseData | None:
    """Search Crunchbase for a person and scrape their profile.

    Tries three layers in order:
    1. Autocomplete API to find the person slug → fetch profile → __NEXT_DATA__
    2. Direct URL guess from name → __NEXT_DATA__
    3. DuckDuckGo snippet fallback for funding context
    """
    clean_name = sanitize_input(name)
    clean_company = sanitize_input(company) if company else None

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        # Layer 2 first: use autocomplete to find the correct person slug
        profile_url = await _find_via_autocomplete(client, clean_name, clean_company)

        # If autocomplete didn't find anything, try guessing the URL
        if not profile_url:
            profile_url = _guess_profile_url(clean_name)

        # Layer 1: fetch the profile page and extract __NEXT_DATA__
        if profile_url:
            await random_delay(0.5, 1.5)
            data = await _fetch_and_parse_profile(client, profile_url)
            if data and _has_useful_data(data):
                return data

        # Layer 3: DuckDuckGo snippet fallback
        return await _ddg_snippet_fallback(clean_name, clean_company)


# ---------------------------------------------------------------------------
# Layer 1: __NEXT_DATA__ JSON extraction
# ---------------------------------------------------------------------------

async def _fetch_and_parse_profile(
    client: httpx.AsyncClient, url: str
) -> CrunchbaseData | None:
    """Fetch a Crunchbase profile page and extract data from __NEXT_DATA__."""
    if not is_safe_url(url):
        return None

    resp = await fetch_with_retry(client, url, headers=get_headers(), max_retries=2)
    if not resp or resp.status_code != 200:
        return None

    html = resp.text

    # Try __NEXT_DATA__ first (richest data source)
    data = _parse_next_data(html, url)
    if data and _has_useful_data(data):
        return data

    # Fall back to HTML parsing
    return _parse_html(html, url)


def _parse_next_data(html: str, profile_url: str) -> CrunchbaseData | None:
    """Extract structured data from Crunchbase's __NEXT_DATA__ JSON blob."""
    # Find the __NEXT_DATA__ script tag
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None

    try:
        next_data = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return None

    # Navigate to the page props — Crunchbase uses several nested structures
    page_props = _deep_get(next_data, "props", "pageProps")
    if not page_props:
        return None

    # Try multiple known key paths for person data
    entity = (
        _deep_get(page_props, "entity")
        or _deep_get(page_props, "data", "entity")
        or _deep_get(page_props, "component", "entity")
        or page_props
    )

    properties = _deep_get(entity, "properties") or entity

    # Extract fields
    title = (
        _deep_get(properties, "title")
        or _deep_get(properties, "primary_role")
        or _deep_get(properties, "role_name")
    )

    company_name = (
        _deep_get(properties, "primary_organization", "value")
        or _deep_get(properties, "organization_name")
        or _deep_get(properties, "org_name")
    )

    description = (
        _deep_get(properties, "short_description")
        or _deep_get(properties, "description")
        or _deep_get(properties, "bio")
    )

    location = (
        _deep_get(properties, "location_identifiers", 0, "value")
        or _deep_get(properties, "location_group_identifiers", 0, "value")
        or _deep_get(properties, "city_name")
    )

    # Extract funding rounds
    funding_rounds = []
    investors = []
    total_funding = None

    # Try to find funding data in various locations
    cards = _deep_get(entity, "cards") or _deep_get(page_props, "cards") or {}

    # Check for funding_rounds card
    funding_card = (
        cards.get("funding_rounds")
        or cards.get("raised_funding_rounds")
        or cards.get("investments")
    )
    if isinstance(funding_card, list):
        for fr in funding_card:
            if isinstance(fr, dict):
                round_info = {
                    "type": fr.get("funding_type") or fr.get("investment_type") or "",
                    "amount": _format_money(fr.get("money_raised", {}).get("value")),
                    "date": fr.get("announced_on") or fr.get("closed_on") or "",
                    "lead_investors": [],
                }
                # Extract lead investors
                for inv in fr.get("lead_investor_identifiers", []):
                    inv_name = inv.get("value") if isinstance(inv, dict) else str(inv)
                    if inv_name:
                        round_info["lead_investors"].append(inv_name)
                        if inv_name not in investors:
                            investors.append(inv_name)
                funding_rounds.append(round_info)

    # Total funding
    total_funding_raw = (
        _deep_get(properties, "total_funding_usd")
        or _deep_get(properties, "funding_total", "value")
    )
    if total_funding_raw:
        total_funding = _format_money(total_funding_raw)

    # Prior companies
    prior_companies = []
    jobs = cards.get("jobs") or cards.get("experience") or []
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict):
                org = (
                    job.get("organization_name")
                    or _deep_get(job, "organization_identifier", "value")
                )
                if org and org not in prior_companies:
                    prior_companies.append(org)

    return CrunchbaseData(
        profile_url=profile_url,
        title=clean_scraped_text(str(title)) if title else None,
        company_name=clean_scraped_text(str(company_name)) if company_name else None,
        company_description=clean_scraped_text(str(description))[:500] if description else None,
        funding_rounds=funding_rounds[:10],
        total_funding=total_funding,
        prior_companies=prior_companies[:10],
        location=clean_scraped_text(str(location)) if location else None,
        investors=investors[:20],
    )


def _parse_html(html: str, profile_url: str) -> CrunchbaseData | None:
    """Fall back to HTML parsing if __NEXT_DATA__ is unavailable."""
    soup = BeautifulSoup(html, "lxml")

    title = None
    company_name = None
    description = None
    prior_companies: list[str] = []

    page_text = clean_scraped_text(soup.get_text(separator=" ", strip=True))

    title_tag = soup.find("h1")
    if title_tag:
        title = clean_scraped_text(title_tag.get_text(strip=True))

    # Extract company references from links
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/organization/" in href:
            org_name = link.get_text(strip=True)
            if org_name and len(org_name) < 100:
                if not company_name:
                    company_name = org_name
                else:
                    prior_companies.append(org_name)

    description = page_text[:500] if page_text else None

    # Try to extract funding info from page text
    total_funding = None
    funding_match = re.search(
        r"\$[\d,.]+[MBK]?\s*(?:total\s+)?(?:funding|raised)",
        page_text or "",
        re.IGNORECASE,
    )
    if funding_match:
        total_funding = funding_match.group(0).strip()

    return CrunchbaseData(
        profile_url=profile_url,
        title=title,
        company_name=company_name,
        company_description=description,
        prior_companies=prior_companies[:10],
        total_funding=total_funding,
    )


# ---------------------------------------------------------------------------
# Layer 2: Autocomplete API for person slug discovery
# ---------------------------------------------------------------------------

async def _find_via_autocomplete(
    client: httpx.AsyncClient, name: str, company: str | None = None
) -> str | None:
    """Use Crunchbase's autocomplete API to find a person's profile URL."""
    query = name
    if company:
        query += f" {company}"

    autocomplete_url = f"{CRUNCHBASE_BASE}/v4/data/autocompletes"
    params = {
        "query": query,
        "collection_ids": "people",
        "limit": "5",
    }

    resp = await fetch_with_retry(
        client,
        autocomplete_url,
        headers=get_headers(),
        params=params,
        max_retries=2,
        retry_on=(429, 999),  # Don't retry 403 here — it may be expected
    )

    if not resp or resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except (json.JSONDecodeError, TypeError):
        return None

    entities = data.get("entities", [])
    if not entities:
        return None

    # Find the best match — prefer exact name match
    name_lower = name.lower()
    for entity in entities:
        identifier = entity.get("identifier", {})
        entity_name = (identifier.get("value") or "").lower()
        permalink = identifier.get("permalink") or entity.get("permalink")

        if not permalink:
            continue

        # Exact or close name match
        if entity_name == name_lower or name_lower in entity_name:
            url = f"{CRUNCHBASE_BASE}/person/{permalink}"
            print(f"[crunchbase] Autocomplete match: {entity_name} → {url}", flush=True)
            return url

    # If no exact match, use the first result
    first = entities[0]
    permalink = _deep_get(first, "identifier", "permalink") or first.get("permalink")
    if permalink:
        url = f"{CRUNCHBASE_BASE}/person/{permalink}"
        print(f"[crunchbase] Autocomplete first result → {url}", flush=True)
        return url

    return None


def _guess_profile_url(name: str) -> str:
    """Guess the Crunchbase profile URL from a person's name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{CRUNCHBASE_BASE}/person/{slug}"


# ---------------------------------------------------------------------------
# Layer 3: DuckDuckGo snippet fallback
# ---------------------------------------------------------------------------

async def _ddg_snippet_fallback(
    name: str, company: str | None = None
) -> CrunchbaseData | None:
    """Search DDG for Crunchbase mentions and parse funding info from snippets."""
    from scraper.multi_search import multi_search

    query_parts = [f'"crunchbase.com" {name}']
    if company:
        query_parts.append(company)
    query_parts.append("funding")
    query = " ".join(query_parts)

    results = multi_search(query, max_results=5)
    if not results:
        return None

    # Collect data from search snippets
    description_parts = []
    funding_rounds = []
    total_funding = None
    investors = []
    profile_url = None
    company_name = None

    for result in results:
        href = result.get("href", "")
        body = result.get("body", "")
        title = result.get("title", "")

        # Capture Crunchbase profile URL if found
        if "crunchbase.com/person/" in href and not profile_url:
            profile_url = href
        elif "crunchbase.com/organization/" in href and not company_name:
            # Extract company name from title
            company_name = re.sub(
                r"\s*[-|·]\s*Crunchbase.*$", "", title, flags=re.IGNORECASE
            ).strip()

        # Parse funding mentions from snippets
        if body:
            description_parts.append(body)

            # Total funding: "$X raised" or "raised $X"
            funding_match = re.search(
                r"(?:raised?\s+)?\$(\d[\d,.]*\s*[MBK](?:illion)?)",
                body,
                re.IGNORECASE,
            )
            if funding_match and not total_funding:
                total_funding = f"${funding_match.group(1)}"

            # Funding round types: "Series A", "Seed", etc.
            round_matches = re.findall(
                r"((?:Series [A-Z]|Seed|Pre-Seed|Angel|Venture|Growth|Convertible)\s*(?:round)?)"
                r"(?:\s+(?:of|for|worth))?\s*\$?([\d,.]+\s*[MBK](?:illion)?)?",
                body,
                re.IGNORECASE,
            )
            for round_type, amount in round_matches:
                round_info = {
                    "type": round_type.strip(),
                    "amount": f"${amount}" if amount else "",
                    "date": "",
                    "lead_investors": [],
                }
                if round_info not in funding_rounds:
                    funding_rounds.append(round_info)

            # Investor names: "led by X" or "backed by X, Y"
            investor_match = re.search(
                r"(?:led by|backed by|investors?\s+include)\s+([^.]+)",
                body,
                re.IGNORECASE,
            )
            if investor_match:
                inv_text = investor_match.group(1)
                for inv in re.split(r",\s*|\s+and\s+", inv_text):
                    inv = inv.strip().rstrip(".")
                    if inv and len(inv) < 50 and inv not in investors:
                        investors.append(inv)

    if not description_parts and not profile_url:
        return None

    return CrunchbaseData(
        profile_url=profile_url,
        company_name=company_name,
        company_description=(" ".join(description_parts))[:500] if description_parts else None,
        funding_rounds=funding_rounds[:10],
        total_funding=total_funding,
        investors=investors[:20],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_get(obj, *keys):
    """Safely navigate nested dicts/lists."""
    for key in keys:
        if obj is None:
            return None
        if isinstance(key, int):
            if isinstance(obj, list) and len(obj) > key:
                obj = obj[key]
            else:
                return None
        elif isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _format_money(value) -> str | None:
    """Format a numeric value as a dollar amount."""
    if value is None:
        return None
    try:
        num = float(value)
        if num >= 1_000_000_000:
            return f"${num / 1_000_000_000:.1f}B"
        elif num >= 1_000_000:
            return f"${num / 1_000_000:.1f}M"
        elif num >= 1_000:
            return f"${num / 1_000:.0f}K"
        else:
            return f"${num:,.0f}"
    except (ValueError, TypeError):
        return str(value)


def _has_useful_data(data: CrunchbaseData) -> bool:
    """Check if a CrunchbaseData has more than just a URL."""
    return bool(
        data.company_name
        or data.company_description
        or data.funding_rounds
        or data.total_funding
        or data.prior_companies
        or data.investors
    )
