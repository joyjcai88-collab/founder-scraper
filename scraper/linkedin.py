"""LinkedIn profile scraper via RapidAPI (Fresh LinkedIn Profile Data).

Uses the "Fresh LinkedIn Profile Data" API on RapidAPI to fetch
any public LinkedIn profile by searching for a person's name.

Setup:
1. Subscribe at https://rapidapi.com/freshdata-freshdata-default/api/fresh-linkedin-profile-data
2. Copy your RapidAPI key
3. Set RAPIDAPI_KEY=your-key in .env
"""

from __future__ import annotations

import os
from typing import Optional, List, Dict

import httpx

from models.founder import LinkedInData
from scraper.safety import clean_scraped_text, sanitize_input

RAPIDAPI_HOST = "fresh-linkedin-profile-data.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}"


def _get_headers() -> dict:
    """Build RapidAPI request headers."""
    api_key = os.getenv("RAPIDAPI_KEY", "")
    return {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }


async def _search_linkedin_url(name: str, company: Optional[str] = None) -> Optional[str]:
    """Search for a person's LinkedIn profile URL via the Google search endpoint."""
    headers = _get_headers()

    # Build search query
    query = sanitize_input(name)
    if company:
        query += f" {sanitize_input(company)}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{RAPIDAPI_BASE}/search-linkedin-profiles",
                headers=headers,
                params={
                    "query": query,
                    "type": "person",
                    "limit": "3",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # The API returns a list of profile results
        profiles = data.get("data", [])
        if not profiles:
            return None

        # Return the first match's LinkedIn URL
        return profiles[0].get("linkedin_url") or profiles[0].get("profile_url")

    except Exception:
        return None


async def _fetch_profile(linkedin_url: str) -> Optional[Dict]:
    """Fetch full LinkedIn profile data by URL."""
    headers = _get_headers()

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{RAPIDAPI_BASE}/get-linkedin-profile",
                headers=headers,
                params={"linkedin_url": linkedin_url},
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", data)

    except Exception:
        return None


def _parse_experience(raw_experience: list) -> List[Dict]:
    """Parse work experience entries from API response."""
    results = []
    for exp in (raw_experience or []):
        entry = {
            "title": exp.get("title", ""),
            "company": exp.get("company", "") or exp.get("company_name", ""),
            "start_date": exp.get("start_date", "") or exp.get("starts_at", ""),
            "end_date": exp.get("end_date", "") or exp.get("ends_at", "") or "Present",
            "location": exp.get("location", ""),
            "description": clean_scraped_text(exp.get("description", "") or "")[:300],
        }
        # Handle nested date objects
        if isinstance(entry["start_date"], dict):
            y = entry["start_date"].get("year", "")
            m = entry["start_date"].get("month", "")
            entry["start_date"] = f"{m}/{y}" if m else str(y)
        if isinstance(entry["end_date"], dict):
            y = entry["end_date"].get("year", "")
            m = entry["end_date"].get("month", "")
            entry["end_date"] = f"{m}/{y}" if m else str(y)

        if entry["title"] or entry["company"]:
            results.append(entry)
    return results


def _parse_education(raw_education: list) -> List[Dict]:
    """Parse education entries from API response."""
    results = []
    for edu in (raw_education or []):
        entry = {
            "school": edu.get("school", "") or edu.get("school_name", ""),
            "degree": edu.get("degree", "") or edu.get("degree_name", ""),
            "field": edu.get("field_of_study", "") or edu.get("field", "") or edu.get("major", ""),
            "start_date": edu.get("start_date", "") or edu.get("starts_at", ""),
            "end_date": edu.get("end_date", "") or edu.get("ends_at", ""),
        }
        if isinstance(entry["start_date"], dict):
            entry["start_date"] = str(entry["start_date"].get("year", ""))
        if isinstance(entry["end_date"], dict):
            entry["end_date"] = str(entry["end_date"].get("year", ""))

        if entry["school"]:
            results.append(entry)
    return results


def _parse_skills(raw_skills: list) -> List[str]:
    """Parse skills list from API response."""
    skills = []
    for skill in (raw_skills or []):
        if isinstance(skill, str):
            skills.append(skill)
        elif isinstance(skill, dict):
            name = skill.get("name", "") or skill.get("skill", "")
            if name:
                skills.append(name)
    return skills


async def scrape_linkedin(name: str, company: Optional[str] = None) -> Optional[LinkedInData]:
    """Search for and scrape a LinkedIn profile via RapidAPI."""
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        return None

    # Step 1: Search for the person's LinkedIn URL
    linkedin_url = await _search_linkedin_url(name, company)
    if not linkedin_url:
        return None

    # Step 2: Fetch full profile
    profile = await _fetch_profile(linkedin_url)
    if not profile:
        return None

    # Step 3: Parse into LinkedInData
    experience = _parse_experience(
        profile.get("experiences", []) or profile.get("experience", [])
    )
    education = _parse_education(
        profile.get("education", [])
    )
    skills = _parse_skills(
        profile.get("skills", [])
    )

    # Parse certifications
    certs = []
    for cert in (profile.get("certifications", []) or []):
        c = {
            "name": cert.get("name", ""),
            "authority": cert.get("authority", "") or cert.get("issuing_organization", ""),
        }
        if c["name"]:
            certs.append(c)

    # Parse languages
    languages = []
    for lang in (profile.get("languages", []) or []):
        if isinstance(lang, str):
            languages.append(lang)
        elif isinstance(lang, dict):
            name_val = lang.get("name", "") or lang.get("language", "")
            if name_val:
                languages.append(name_val)

    return LinkedInData(
        profile_url=linkedin_url,
        headline=profile.get("headline", "") or profile.get("sub_title", ""),
        summary=clean_scraped_text(profile.get("summary", "") or profile.get("about", "") or "")[:1000],
        location=(
            profile.get("location", "")
            or profile.get("city", "")
            or profile.get("country", "")
        ),
        followers=int(profile.get("follower_count", 0) or profile.get("followers", 0) or 0),
        connections=int(profile.get("connections", 0) or profile.get("connection_count", 0) or 0),
        experience=experience[:10],
        education=education[:5],
        skills=skills[:30],
        certifications=certs[:10],
        languages=languages[:10],
    )


# --- Keep OAuth helpers for the "Connect LinkedIn" button (optional) ---

def is_linkedin_configured() -> bool:
    """Check if LinkedIn OAuth credentials are set (for optional self-auth)."""
    return bool(
        os.getenv("LINKEDIN_CLIENT_ID")
        and os.getenv("LINKEDIN_CLIENT_SECRET")
        and os.getenv("LINKEDIN_REDIRECT_URI")
    )


def build_auth_url(state: str = "linkedin_oauth") -> str:
    """Build the LinkedIn OAuth authorization URL."""
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": os.getenv("LINKEDIN_CLIENT_ID", ""),
        "redirect_uri": os.getenv("LINKEDIN_REDIRECT_URI", ""),
        "state": state,
        "scope": "openid profile email",
    }
    return f"https://www.linkedin.com/oauth/v2/authorization?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> Optional[str]:
    """Exchange an authorization code for an access token."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": os.getenv("LINKEDIN_REDIRECT_URI", ""),
        "client_id": os.getenv("LINKEDIN_CLIENT_ID", ""),
        "client_secret": os.getenv("LINKEDIN_CLIENT_SECRET", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json().get("access_token")
    except Exception:
        return None


async def fetch_linkedin_profile(access_token: str) -> Optional[Dict]:
    """Fetch the authenticated user's profile via OpenID Connect."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "picture": data.get("picture", ""),
        }
    except Exception:
        return None
