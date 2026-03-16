"""Crunchbase public page scraper."""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from models.founder import CrunchbaseData
from scraper.safety import clean_scraped_text, is_safe_url, sanitize_input

TIMEOUT = 15
CRUNCHBASE_BASE = "https://www.crunchbase.com"
SEARCH_URL = "https://www.crunchbase.com/textsearch"


async def scrape_crunchbase(name: str, company: str | None = None) -> CrunchbaseData | None:
    """Search Crunchbase for a person and scrape their public profile."""
    query = sanitize_input(name)
    if company:
        query += f" {sanitize_input(company)}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        # Try to find the person's profile via search
        search_resp = await client.get(
            SEARCH_URL,
            params={"q": query},
            headers=headers,
        )

        if search_resp.status_code != 200:
            return None

        soup = BeautifulSoup(search_resp.text, "lxml")

        # Look for person profile links in search results
        person_link = None
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/person/" in href:
                person_link = href if href.startswith("http") else f"{CRUNCHBASE_BASE}{href}"
                break

        if not person_link or not is_safe_url(person_link):
            return _fallback_data(query, soup)

        # Fetch the person's profile page
        profile_resp = await client.get(person_link, headers=headers)
        if profile_resp.status_code != 200:
            return _fallback_data(query, soup)

        return _parse_profile(profile_resp.text, person_link)


def _fallback_data(query: str, soup: BeautifulSoup) -> CrunchbaseData | None:
    """Extract whatever we can from search results if profile page fails."""
    text = clean_scraped_text(soup.get_text(separator=" ", strip=True))
    if not text or len(text) < 20:
        return None

    return CrunchbaseData(
        company_description=text[:500],
    )


def _parse_profile(html: str, profile_url: str) -> CrunchbaseData:
    """Parse a Crunchbase person profile page."""
    soup = BeautifulSoup(html, "lxml")

    title = None
    company_name = None
    description = None
    location = None
    prior_companies: list[str] = []

    # Try to extract structured info from the page
    # Crunchbase uses dynamic rendering, so static scraping is limited
    page_text = clean_scraped_text(soup.get_text(separator=" ", strip=True))

    # Look for common patterns in the page text
    title_tag = soup.find("h1")
    if title_tag:
        title = clean_scraped_text(title_tag.get_text(strip=True))

    # Extract any company references
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

    return CrunchbaseData(
        profile_url=profile_url,
        title=title,
        company_name=company_name,
        company_description=description,
        prior_companies=prior_companies[:10],
        location=location,
    )
