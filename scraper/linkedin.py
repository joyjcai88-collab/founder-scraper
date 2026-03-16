"""LinkedIn API scraper using the official REST API.

Requires a LinkedIn access token. Set LINKEDIN_ACCESS_TOKEN in your .env file.

To get an access token:
1. Create an app at https://www.linkedin.com/developers/apps
2. Request the "Sign In with LinkedIn using OpenID Connect" product
3. For accessing other profiles, apply for partner-level access
   (Talent Solutions or Sales Navigator API)
4. Use OAuth 2.0 authorization code flow to get an access token
5. Add LINKEDIN_ACCESS_TOKEN=your-token to your .env file

Note: With standard developer access, you can only read the authenticated
user's own profile. To look up other founders, you need partner access
or can use the vanity name lookup if your app has People Search permissions.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import httpx

from models.founder import LinkedInData
from scraper.safety import clean_scraped_text, sanitize_input

API_BASE = "https://api.linkedin.com/v2"
TIMEOUT = 15
API_VERSION = "202502"


def _get_headers() -> Optional[dict]:
    """Build auth headers from the access token, or return None if not configured."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _extract_vanity_name(name: str) -> Optional[str]:
    """Extract a LinkedIn vanity name if the input looks like a LinkedIn URL."""
    match = re.search(r"linkedin\.com/in/([A-Za-z0-9_-]+)", name)
    if match:
        return match.group(1)
    return None


async def scrape_linkedin(name: str, company: Optional[str] = None) -> Optional[LinkedInData]:
    """Fetch LinkedIn profile data via the official API."""
    headers = _get_headers()
    if not headers:
        return None

    query = sanitize_input(name)
    vanity = _extract_vanity_name(query)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        if vanity:
            # Try vanity name lookup (requires People Search permissions)
            data = await _fetch_by_vanity(client, headers, vanity)
        else:
            # Try searching for the person
            data = await _search_person(client, headers, query, company)

        if not data:
            # Fall back to authenticated user's own profile (always works)
            data = await _fetch_own_profile(client, headers)

        return data


async def _fetch_by_vanity(
    client: httpx.AsyncClient, headers: dict, vanity: str
) -> Optional[LinkedInData]:
    """Look up a profile by vanity name (requires partner access)."""
    resp = await client.get(
        f"{API_BASE}/people/(vanityName:{vanity})",
        headers=headers,
        params={
            "projection": "(id,firstName,lastName,headline,vanityName,"
            "localizedHeadline,localizedFirstName,localizedLastName)"
        },
    )
    if resp.status_code != 200:
        return None

    profile = resp.json()
    return _parse_profile_response(profile, vanity)


async def _search_person(
    client: httpx.AsyncClient,
    headers: dict,
    name: str,
    company: Optional[str],
) -> Optional[LinkedInData]:
    """Search for a person by name (requires People Search permissions)."""
    query = sanitize_input(name)
    if company:
        query += f" {sanitize_input(company)}"

    resp = await client.get(
        f"{API_BASE}/people",
        headers=headers,
        params={
            "q": "search",
            "keywords": query,
            "count": 1,
        },
    )
    if resp.status_code != 200:
        return None

    results = resp.json().get("elements", [])
    if not results:
        return None

    person = results[0]
    vanity = person.get("vanityName")
    return _parse_profile_response(person, vanity)


async def _fetch_own_profile(
    client: httpx.AsyncClient, headers: dict
) -> Optional[LinkedInData]:
    """Fetch the authenticated user's own profile (always available)."""
    resp = await client.get(
        f"{API_BASE}/userinfo",
        headers=headers,
    )
    if resp.status_code != 200:
        return None

    data = resp.json()

    # Also try the profile endpoint for richer data
    profile_resp = await client.get(
        f"{API_BASE}/me",
        headers=headers,
        params={
            "projection": "(id,firstName,lastName,headline,vanityName,"
            "localizedHeadline,localizedFirstName,localizedLastName,"
            "profilePicture,industryName)"
        },
    )

    profile_data = profile_resp.json() if profile_resp.status_code == 200 else {}

    first_name = data.get("given_name", "")
    last_name = data.get("family_name", "")
    headline = profile_data.get("localizedHeadline") or data.get("name", "")

    # Try to get positions
    positions = await _fetch_positions(client, headers)
    education = await _fetch_education(client, headers)

    return LinkedInData(
        profile_url=f"https://www.linkedin.com/in/{profile_data.get('vanityName', '')}",
        headline=clean_scraped_text(headline) if headline else None,
        summary=clean_scraped_text(data.get("email", "")) if data.get("email") else None,
        location=data.get("locale", {}).get("country"),
        industry=profile_data.get("industryName"),
        positions=positions,
        education=education,
    )


async def _fetch_positions(
    client: httpx.AsyncClient, headers: dict
) -> list:
    """Fetch position/experience data."""
    resp = await client.get(
        f"{API_BASE}/positions",
        headers=headers,
        params={"q": "members", "projection": "(elements*(title,companyName))"},
    )
    if resp.status_code != 200:
        return []

    positions = []
    for elem in resp.json().get("elements", [])[:10]:
        title = elem.get("title", {})
        company = elem.get("companyName", {})
        if isinstance(title, dict):
            title = title.get("localized", {}).get("en_US", "")
        if isinstance(company, dict):
            company = company.get("localized", {}).get("en_US", "")
        positions.append({
            "title": clean_scraped_text(str(title)),
            "company": clean_scraped_text(str(company)),
        })

    return positions


async def _fetch_education(
    client: httpx.AsyncClient, headers: dict
) -> list:
    """Fetch education data."""
    resp = await client.get(
        f"{API_BASE}/educations",
        headers=headers,
        params={"q": "members"},
    )
    if resp.status_code != 200:
        return []

    education = []
    for elem in resp.json().get("elements", [])[:5]:
        school = elem.get("schoolName", {})
        degree = elem.get("degreeName", {})
        if isinstance(school, dict):
            school = school.get("localized", {}).get("en_US", "")
        if isinstance(degree, dict):
            degree = degree.get("localized", {}).get("en_US", "")
        education.append({
            "school": clean_scraped_text(str(school)),
            "degree": clean_scraped_text(str(degree)),
        })

    return education


def _parse_profile_response(
    profile: dict, vanity: Optional[str] = None
) -> LinkedInData:
    """Parse a LinkedIn API profile response into our data model."""
    first = profile.get("localizedFirstName", "")
    last = profile.get("localizedLastName", "")
    headline = profile.get("localizedHeadline", "")

    profile_url = None
    if vanity:
        profile_url = f"https://www.linkedin.com/in/{vanity}"

    return LinkedInData(
        profile_url=profile_url,
        headline=clean_scraped_text(headline) if headline else None,
        industry=profile.get("industryName"),
    )
