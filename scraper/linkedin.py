"""LinkedIn public profile scraper — works for ANY person, no API key needed.

Strategy:
1. Search DuckDuckGo for "site:linkedin.com/in {name} {company}"
2. Fetch the public LinkedIn profile page
3. Extract structured data from OpenGraph meta tags + JSON-LD + HTML parsing

Free and works for any public LinkedIn profile, not just the authenticated user.

Optional: LinkedIn OAuth still available for the "Connect LinkedIn" button,
which gives verified identity of the logged-in user.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional, List, Dict
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from models.founder import LinkedInData
from scraper.safety import clean_scraped_text, sanitize_input

TIMEOUT = 20

# Realistic browser headers to avoid blocks
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


# ---------------------------------------------------------------------------
# Step 1: Find LinkedIn profile URL via DuckDuckGo
# ---------------------------------------------------------------------------

async def _find_linkedin_url(name: str, company: Optional[str] = None) -> Optional[str]:
    """Search DuckDuckGo for a person's LinkedIn profile URL."""
    query = f"site:linkedin.com/in {sanitize_input(name)}"
    if company:
        query += f" {sanitize_input(company)}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=_HEADERS,
            )
            if resp.status_code != 200:
                return None

            # Find linkedin.com/in/ URLs in the results
            pattern = r"https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)"
            matches = re.findall(pattern, resp.text)

            if not matches:
                return None

            # Return the first unique profile slug
            seen = set()
            for slug in matches:
                if slug not in seen and slug not in ("login", "signup", "feed"):
                    return f"https://www.linkedin.com/in/{slug}"
                seen.add(slug)

    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Step 2: Fetch and parse public LinkedIn profile
# ---------------------------------------------------------------------------

async def _fetch_public_profile(url: str) -> Optional[Dict]:
    """Fetch a public LinkedIn profile and extract available data.

    LinkedIn serves limited but useful data to crawlers via:
    - OpenGraph meta tags (og:title, og:description, og:image)
    - JSON-LD structured data (when available)
    - HTML content for public profiles
    """
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, http2=False
        ) as client:
            resp = await client.get(url, headers=_HEADERS)

            # LinkedIn may return 999 for aggressive scraping, but
            # usually 200 for occasional single-page requests
            if resp.status_code not in (200, 301, 302):
                return None

            html = resp.text

    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")
    data: Dict = {"profile_url": url}

    # --- Extract from OpenGraph meta tags ---
    og_title = soup.find("meta", property="og:title")
    if og_title:
        content = og_title.get("content", "")
        data["og_title"] = clean_scraped_text(content)

    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        data["og_description"] = clean_scraped_text(og_desc.get("content", ""))

    og_image = soup.find("meta", property="og:image")
    if og_image:
        data["picture"] = og_image.get("content", "")

    # --- Extract from standard meta description ---
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        data["meta_description"] = clean_scraped_text(meta_desc.get("content", ""))

    # --- Extract from JSON-LD structured data ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            if isinstance(ld, dict):
                if ld.get("@type") == "Person" or "name" in ld:
                    data["jsonld"] = ld
                    break
        except (json.JSONDecodeError, TypeError):
            continue

    # --- Extract from page title ---
    title_tag = soup.find("title")
    if title_tag:
        data["page_title"] = clean_scraped_text(title_tag.get_text(strip=True))

    return data if len(data) > 1 else None


# ---------------------------------------------------------------------------
# Step 3: Parse extracted data into LinkedInData
# ---------------------------------------------------------------------------

def _parse_profile_data(raw: Dict) -> LinkedInData:
    """Convert raw scraped data into a LinkedInData model."""
    profile_url = raw.get("profile_url", "")
    headline = ""
    summary = ""
    location = ""
    experience: List[Dict] = []
    education: List[Dict] = []
    skills: List[str] = []

    # Parse OpenGraph title: "Name - Headline | LinkedIn"
    og_title = raw.get("og_title", "")
    if og_title:
        og_title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", og_title)
        parts = og_title.split(" - ", 1)
        if len(parts) > 1:
            headline = parts[1].strip()

    # Use meta description or og:description for summary
    desc = raw.get("og_description", "") or raw.get("meta_description", "")
    if desc:
        summary = desc[:500]

        # Try to extract location from description
        loc_match = re.search(r"(?:located in|based in|from)\s+([^.·|]+)", desc, re.I)
        if loc_match:
            location = loc_match.group(1).strip()

        # Try to extract experience mentions
        exp_patterns = re.findall(
            r"(?:experience|worked at|working at|formerly at)\s*:?\s*([^.·|]+)",
            desc, re.I
        )
        for exp_text in exp_patterns[:5]:
            experience.append({
                "title": "",
                "company": exp_text.strip(),
                "start_date": "",
                "end_date": "",
            })

        # Try to extract education mentions
        edu_patterns = re.findall(
            r"(?:education|studied at|graduated from|alumni of)\s*:?\s*([^.·|]+)",
            desc, re.I
        )
        for edu_text in edu_patterns[:3]:
            education.append({
                "school": edu_text.strip(),
                "degree": "",
                "field": "",
            })

    # Parse JSON-LD if available (richest data source)
    jsonld = raw.get("jsonld", {})
    if jsonld:
        if jsonld.get("jobTitle"):
            headline = headline or jsonld["jobTitle"]
        if jsonld.get("description"):
            summary = summary or jsonld["description"][:500]

        # Address / location
        addr = jsonld.get("address", {})
        if isinstance(addr, dict):
            loc_parts = [addr.get("addressLocality", ""), addr.get("addressCountry", "")]
            location = location or ", ".join(p for p in loc_parts if p)
        elif isinstance(addr, str):
            location = location or addr

        # Work experience from JSON-LD
        works_for = jsonld.get("worksFor")
        if works_for:
            if not isinstance(works_for, list):
                works_for = [works_for]
            for work in works_for:
                if isinstance(work, dict) and work.get("name"):
                    experience.append({
                        "title": jsonld.get("jobTitle", ""),
                        "company": work["name"],
                        "start_date": "",
                        "end_date": "Present",
                    })

        # Education from JSON-LD
        alumni_of = jsonld.get("alumniOf")
        if alumni_of:
            if not isinstance(alumni_of, list):
                alumni_of = [alumni_of]
            for edu in alumni_of:
                if isinstance(edu, dict) and edu.get("name"):
                    education.append({
                        "school": edu["name"],
                        "degree": "",
                        "field": "",
                    })

        # Skills from JSON-LD
        if jsonld.get("knowsAbout"):
            knows = jsonld["knowsAbout"]
            if isinstance(knows, list):
                skills = [str(s) for s in knows[:30]]
            elif isinstance(knows, str):
                skills = [s.strip() for s in knows.split(",")]

    # Parse headline from page title as fallback
    if not headline:
        page_title = raw.get("page_title", "")
        page_title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", page_title)
        parts = page_title.split(" - ", 1)
        if len(parts) > 1:
            headline = parts[1].strip()

    return LinkedInData(
        profile_url=profile_url,
        headline=headline or None,
        summary=summary or None,
        location=location or None,
        followers=0,
        connections=0,
        experience=experience[:10],
        education=education[:5],
        skills=skills[:30],
        certifications=[],
        languages=[],
    )


# ---------------------------------------------------------------------------
# Main scraper entry point (called by enricher.py)
# ---------------------------------------------------------------------------

async def scrape_linkedin(name: str, company: Optional[str] = None) -> Optional[LinkedInData]:
    """Search for and scrape any person's public LinkedIn profile.

    No API key needed. Uses DuckDuckGo to find the profile URL,
    then extracts data from the public page's meta tags and JSON-LD.
    """
    # Step 1: Find the LinkedIn profile URL
    linkedin_url = await _find_linkedin_url(name, company)
    if not linkedin_url:
        return None

    # Step 2: Fetch and parse the public profile
    raw_data = await _fetch_public_profile(linkedin_url)
    if not raw_data:
        # Even if we can't scrape the page, return the URL as a source
        return LinkedInData(profile_url=linkedin_url)

    # Step 3: Parse into structured data
    return _parse_profile_data(raw_data)


# ---------------------------------------------------------------------------
# OAuth helpers (for optional "Connect LinkedIn" button)
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
