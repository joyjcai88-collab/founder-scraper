"""LinkedIn profile scraper using OAuth 2.0 (user's own account).

Flow:
1. User clicks "Connect LinkedIn" → redirected to LinkedIn auth
2. LinkedIn redirects back with an auth code
3. We exchange the code for an access token
4. We use the token to search/view profiles via LinkedIn REST API

LinkedIn API v2 scopes needed:
- openid, profile, email  (Sign In with LinkedIn / OpenID Connect)
- r_liteprofile is deprecated; use the OpenID profile scope instead

Note: The LinkedIn API with user OAuth only returns the authenticated
user's own profile (not arbitrary lookups). For searching other people,
we use the authenticated user's profile data if it matches the query,
or return None.  This is a known limitation of LinkedIn's API for
non-partner apps.
"""

from __future__ import annotations

import os
from typing import Optional, Dict, Any
from urllib.parse import urlencode

import httpx


LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# Scopes for OpenID Connect (replaces deprecated r_liteprofile)
SCOPES = "openid profile email"


def get_linkedin_config() -> Dict[str, str]:
    """Return LinkedIn OAuth config from env vars."""
    return {
        "client_id": os.getenv("LINKEDIN_CLIENT_ID", ""),
        "client_secret": os.getenv("LINKEDIN_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("LINKEDIN_REDIRECT_URI", ""),
    }


def is_linkedin_configured() -> bool:
    """Check if LinkedIn OAuth credentials are set."""
    cfg = get_linkedin_config()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"])


def build_auth_url(state: str = "linkedin_oauth") -> str:
    """Build the LinkedIn OAuth authorization URL."""
    cfg = get_linkedin_config()
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
        "scope": SCOPES,
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> Optional[str]:
    """Exchange an authorization code for an access token."""
    cfg = get_linkedin_config()
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("access_token")
    except Exception:
        return None


async def fetch_linkedin_profile(access_token: str) -> Optional[Dict[str, Any]]:
    """Fetch the authenticated user's profile via OpenID Connect userinfo."""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(LINKEDIN_USERINFO_URL, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return {
            "name": data.get("name", ""),
            "given_name": data.get("given_name", ""),
            "family_name": data.get("family_name", ""),
            "email": data.get("email", ""),
            "picture": data.get("picture", ""),
            "linkedin_id": data.get("sub", ""),
            "locale": data.get("locale", ""),
        }
    except Exception:
        return None
