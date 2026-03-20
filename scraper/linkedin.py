"""LinkedIn profile data via official LinkedIn API (OAuth 2.0).

Uses LinkedIn's OpenID Connect + Profile API to fetch the authenticated
user's own profile data. Free — no per-request charges.

Setup:
1. Create an app at https://www.linkedin.com/developers/apps
2. Add the "Sign In with LinkedIn using OpenID Connect" product
3. Set redirect URI (e.g. http://localhost:8000/api/linkedin/callback)
4. Add LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI to .env

Limitation: LinkedIn's API only returns the authenticated user's own profile.
For looking up other founders, PDL and Perplexity remain the primary sources.
"""

from __future__ import annotations

import os
from typing import Optional, Dict
from urllib.parse import urlencode

import httpx

from models.founder import LinkedInData
from scraper.safety import clean_scraped_text


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def is_linkedin_configured() -> bool:
    """Check if LinkedIn OAuth credentials are set."""
    return bool(
        os.getenv("LINKEDIN_CLIENT_ID")
        and os.getenv("LINKEDIN_CLIENT_SECRET")
        and os.getenv("LINKEDIN_REDIRECT_URI")
    )


def build_auth_url(state: str = "linkedin_oauth") -> str:
    """Build the LinkedIn OAuth authorization URL."""
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
    """Fetch the authenticated user's profile via OpenID Connect userinfo."""
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
            "given_name": data.get("given_name", ""),
            "family_name": data.get("family_name", ""),
            "email": data.get("email", ""),
            "picture": data.get("picture", ""),
            "linkedin_id": data.get("sub", ""),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Profile builder — creates LinkedInData from the stored OAuth profile
# ---------------------------------------------------------------------------

def build_linkedin_data_from_oauth(profile: Dict) -> Optional[LinkedInData]:
    """Convert an OAuth userinfo profile dict into a LinkedInData model.

    The OpenID Connect userinfo endpoint returns limited fields:
    name, email, picture, sub (LinkedIn member ID).
    """
    if not profile:
        return None

    name = profile.get("name", "")
    if not name:
        return None

    return LinkedInData(
        profile_url=f"https://www.linkedin.com/in/{profile.get('linkedin_id', '')}",
        headline=name,
        summary=f"LinkedIn authenticated user: {name}",
        location="",
        followers=0,
        connections=0,
        experience=[],
        education=[],
        skills=[],
        certifications=[],
        languages=[],
    )


# ---------------------------------------------------------------------------
# Scraper entry point (used by enricher.py)
# ---------------------------------------------------------------------------

async def scrape_linkedin(name: str, company: Optional[str] = None) -> Optional[LinkedInData]:
    """Attempt to return LinkedIn data for the queried person.

    Since the official LinkedIn API only returns the authenticated user's
    own profile, this function checks if the connected user's name matches
    the query. If not, returns None (PDL/Perplexity will cover the gap).
    """
    # Import here to avoid circular dependency — server stores the token
    try:
        from server import _linkedin_profiles
    except ImportError:
        return None

    if not _linkedin_profiles:
        return None

    profile = list(_linkedin_profiles.values())[0]
    if not profile:
        return None

    # Check if the connected LinkedIn user matches the search query
    connected_name = (profile.get("name", "") or "").lower()
    query_name = name.lower().strip()

    # Fuzzy match: check if query name is contained in connected name or vice versa
    name_parts = query_name.split()
    matches = any(part in connected_name for part in name_parts if len(part) > 2)

    if not matches:
        # The connected user doesn't match the search — can't look up other profiles
        return None

    return build_linkedin_data_from_oauth(profile)
