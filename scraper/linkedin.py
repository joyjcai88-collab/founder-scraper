"""LinkedIn public profile scraper — works for ANY person, no API key needed.

Strategy:
1. Search DuckDuckGo for "site:linkedin.com/in {name} {company}"
   - Also captures search snippet text for augmentation
2. Fetch the public LinkedIn profile page
3. Extract structured data from:
   - OpenGraph meta tags (og:title, og:description)
   - JSON-LD structured data (Person schema)
   - Embedded <code> tags (Voyager API data)
   - HTML parsing fallbacks
4. Augment with DDG snippet data when profile scrape is sparse

Improvements over basic meta-tag approach:
- Parses LinkedIn's middle-dot delimited og:description properly
- Extracts sameAs, memberOf, alumniOf from JSON-LD
- Scans <code> tags for Voyager API JSON fragments
- Uses retry with exponential backoff on 999/429
- Rotates User-Agent strings

Optional: LinkedIn OAuth still available for the "Connect LinkedIn" button,
which gives verified identity of the logged-in user.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlencode, unquote

import httpx
from bs4 import BeautifulSoup

from models.founder import LinkedInData
from scraper.retry import fetch_with_retry, get_headers, get_random_ua, random_delay
from scraper.safety import clean_scraped_text, sanitize_input

TIMEOUT = 20


# ---------------------------------------------------------------------------
# Step 1: Find LinkedIn profile URL via DuckDuckGo (with snippet capture)
# ---------------------------------------------------------------------------

async def _find_linkedin_url(
    name: str, company: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """Search for a person's LinkedIn profile URL using multi-engine search.

    Returns (url, snippet_text) — snippet_text can augment sparse profiles.
    Uses both DDG and Brave for redundancy.
    """
    from scraper.multi_search import multi_search

    query = f"site:linkedin.com/in {sanitize_input(name)}"
    if company:
        query += f" {sanitize_input(company)}"

    snippet_text = ""

    try:
        results = multi_search(query, max_results=5)

        for result in results:
            href = result.get("href", "")
            body = result.get("body", "")

            # Match LinkedIn profile URLs
            li_match = re.search(
                r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)",
                href,
            )
            if li_match:
                slug = li_match.group(1)
                if slug not in ("login", "signup", "feed", "pulse"):
                    snippet_text = body
                    return f"https://www.linkedin.com/in/{slug}", snippet_text

    except Exception:
        pass

    return None, ""


# ---------------------------------------------------------------------------
# Step 2: Fetch and parse public LinkedIn profile
# ---------------------------------------------------------------------------

async def _fetch_public_profile(url: str) -> Optional[Dict]:
    """Fetch a public LinkedIn profile and extract available data.

    LinkedIn serves limited but useful data to crawlers via:
    - OpenGraph meta tags (og:title, og:description, og:image)
    - JSON-LD structured data (when available)
    - Embedded <code> tags with Voyager API JSON
    - HTML content for public profiles
    """
    await random_delay(0.5, 1.5)

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, http2=False
        ) as client:
            resp = await fetch_with_retry(
                client,
                url,
                headers=get_headers(),
                max_retries=3,
                retry_on=(429, 999),
            )

            if not resp or resp.status_code not in (200, 301, 302):
                return None

            html = resp.text

    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")
    data: Dict = {"profile_url": url}

    # --- Extract from OpenGraph meta tags ---
    og_title = soup.find("meta", property="og:title")
    if og_title:
        data["og_title"] = clean_scraped_text(og_title.get("content", ""))

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

    # --- Scan <code> tags for Voyager API data ---
    code_data = _extract_code_tag_data(soup)
    if code_data:
        data["code_data"] = code_data

    # --- Extract from page title ---
    title_tag = soup.find("title")
    if title_tag:
        data["page_title"] = clean_scraped_text(title_tag.get_text(strip=True))

    return data if len(data) > 1 else None


def _extract_code_tag_data(soup: BeautifulSoup) -> Optional[Dict]:
    """Scan <code> tags for LinkedIn Voyager API JSON fragments.

    LinkedIn sometimes embeds structured profile data in <code> tags,
    which contain JSON objects from the Voyager API.
    """
    extracted = {}

    for code_tag in soup.find_all("code"):
        text = code_tag.string or code_tag.get_text()
        if not text or len(text) < 50:
            continue

        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(obj, dict):
            continue

        # Look for profile data patterns
        included = obj.get("included", [])
        if isinstance(included, list):
            for item in included:
                if not isinstance(item, dict):
                    continue

                recipe = item.get("$type", "") or item.get("$recipeType", "")

                # Experience entries
                if "Position" in recipe or "position" in recipe.lower():
                    title = item.get("title", "")
                    company = item.get("companyName", "")
                    if title or company:
                        extracted.setdefault("experience", []).append({
                            "title": title,
                            "company": company,
                            "start_date": _format_date(item.get("dateRange", {}).get("start")),
                            "end_date": _format_date(item.get("dateRange", {}).get("end")) or "Present",
                        })

                # Education entries
                elif "Education" in recipe or "education" in recipe.lower():
                    school = item.get("schoolName", "")
                    degree = item.get("degreeName", "")
                    field = item.get("fieldOfStudy", "")
                    if school:
                        extracted.setdefault("education", []).append({
                            "school": school,
                            "degree": degree,
                            "field": field,
                        })

                # Skills
                elif "Skill" in recipe or "skill" in recipe.lower():
                    skill_name = item.get("name", "")
                    if skill_name:
                        extracted.setdefault("skills", []).append(skill_name)

                # Profile summary
                elif "Profile" in recipe or "profile" in recipe.lower():
                    if item.get("headline"):
                        extracted["headline"] = item["headline"]
                    if item.get("summary"):
                        extracted["summary"] = item["summary"]
                    if item.get("locationName"):
                        extracted["location"] = item["locationName"]
                    if item.get("industryName"):
                        extracted["industry"] = item["industryName"]

    return extracted if extracted else None


def _format_date(date_obj) -> str:
    """Format a LinkedIn date object ({"month": N, "year": YYYY}) to string."""
    if not date_obj or not isinstance(date_obj, dict):
        return ""
    year = date_obj.get("year", "")
    month = date_obj.get("month", "")
    if year and month:
        return f"{month}/{year}"
    return str(year) if year else ""


# ---------------------------------------------------------------------------
# Step 3: Parse extracted data into LinkedInData
# ---------------------------------------------------------------------------

def _parse_profile_data(raw: Dict, ddg_snippet: str = "") -> LinkedInData:
    """Convert raw scraped data into a LinkedInData model.

    Uses multiple data sources in priority order:
    1. <code> tag Voyager data (richest)
    2. JSON-LD structured data
    3. OpenGraph meta tags (parsed by delimiter)
    4. DDG snippet augmentation (fills gaps)
    """
    profile_url = raw.get("profile_url", "")
    headline = ""
    summary = ""
    location = ""
    followers = 0
    connections = 0
    experience: List[Dict] = []
    education: List[Dict] = []
    skills: List[str] = []

    # --- Source 1: <code> tag Voyager data (highest fidelity) ---
    code_data = raw.get("code_data", {})
    if code_data:
        headline = code_data.get("headline", "")
        summary = code_data.get("summary", "")
        location = code_data.get("location", "")
        experience = code_data.get("experience", [])[:10]
        education = code_data.get("education", [])[:5]
        skills = code_data.get("skills", [])[:30]

    # --- Source 2: JSON-LD structured data ---
    jsonld = raw.get("jsonld", {})
    if jsonld:
        if not headline and jsonld.get("jobTitle"):
            headline = jsonld["jobTitle"]
        if not summary and jsonld.get("description"):
            summary = jsonld["description"][:500]

        # Address / location
        if not location:
            addr = jsonld.get("address", {})
            if isinstance(addr, dict):
                loc_parts = [addr.get("addressLocality", ""), addr.get("addressCountry", "")]
                location = ", ".join(p for p in loc_parts if p)
            elif isinstance(addr, str):
                location = addr

        # Work experience from JSON-LD
        if not experience:
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
        if not education:
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
        if not skills and jsonld.get("knowsAbout"):
            knows = jsonld["knowsAbout"]
            if isinstance(knows, list):
                skills = [str(s) for s in knows[:30]]
            elif isinstance(knows, str):
                skills = [s.strip() for s in knows.split(",")]

        # sameAs links (cross-references to other profiles)
        same_as = jsonld.get("sameAs", [])
        if isinstance(same_as, list):
            for link in same_as:
                if isinstance(link, str) and link.startswith("http"):
                    # Could be used for cross-platform enrichment
                    pass

        # memberOf / affiliation
        if not experience:
            for key in ("memberOf", "affiliation"):
                orgs = jsonld.get(key, [])
                if isinstance(orgs, dict):
                    orgs = [orgs]
                if isinstance(orgs, list):
                    for org in orgs:
                        if isinstance(org, dict) and org.get("name"):
                            experience.append({
                                "title": "Member",
                                "company": org["name"],
                                "start_date": "",
                                "end_date": "",
                            })

    # --- Source 3: OpenGraph meta tags (parsed by delimiter) ---
    desc = raw.get("og_description", "") or raw.get("meta_description", "")
    if desc:
        parsed = _parse_linkedin_description(desc)

        if not headline and parsed.get("headline"):
            headline = parsed["headline"]
        if not location and parsed.get("location"):
            location = parsed["location"]
        if not experience and parsed.get("experience_text"):
            experience.append({
                "title": "",
                "company": parsed["experience_text"],
                "start_date": "",
                "end_date": "",
            })
        if not education and parsed.get("education_text"):
            education.append({
                "school": parsed["education_text"],
                "degree": "",
                "field": "",
            })
        if parsed.get("connections"):
            connections = parsed["connections"]
        if not summary:
            summary = desc[:500]

    # Parse OpenGraph title: "Name - Headline | LinkedIn"
    og_title = raw.get("og_title", "")
    if og_title and not headline:
        og_title_clean = re.sub(r"\s*\|\s*LinkedIn\s*$", "", og_title)
        parts = og_title_clean.split(" - ", 1)
        if len(parts) > 1:
            headline = parts[1].strip()

    # Fallback: page title
    if not headline:
        page_title = raw.get("page_title", "")
        page_title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", page_title)
        parts = page_title.split(" - ", 1)
        if len(parts) > 1:
            headline = parts[1].strip()

    # --- Source 4: DDG snippet augmentation ---
    if ddg_snippet:
        parsed_snippet = _parse_linkedin_description(ddg_snippet)
        if not headline and parsed_snippet.get("headline"):
            headline = parsed_snippet["headline"]
        if not location and parsed_snippet.get("location"):
            location = parsed_snippet["location"]
        if not experience and parsed_snippet.get("experience_text"):
            experience.append({
                "title": "",
                "company": parsed_snippet["experience_text"],
                "start_date": "",
                "end_date": "",
            })
        if not education and parsed_snippet.get("education_text"):
            education.append({
                "school": parsed_snippet["education_text"],
                "degree": "",
                "field": "",
            })

    return LinkedInData(
        profile_url=profile_url,
        headline=headline or None,
        summary=summary or None,
        location=location or None,
        followers=followers,
        connections=connections,
        experience=experience[:10],
        education=education[:5],
        skills=skills[:30],
        certifications=[],
        languages=[],
    )


def _parse_linkedin_description(desc: str) -> Dict:
    """Parse LinkedIn's delimited description format.

    LinkedIn og:description uses middle-dot (\u00b7) or pipe (|) delimiters:
    "Headline \u00b7 Experience: CompanyName \u00b7 Education: SchoolName \u00b7 Location \u00b7 500+ connections"

    This replaces the old regex keyword matching approach.
    """
    result: Dict = {}

    if not desc:
        return result

    # Split by middle-dot, pipe, or em-dash delimiters
    segments = re.split(r'\s*[\u00b7|–—]\s*', desc)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # Connections count: "500+ connections" or "347 connections"
        conn_match = re.search(r'(\d[\d,]*)\+?\s*connections?', segment, re.IGNORECASE)
        if conn_match:
            result["connections"] = int(conn_match.group(1).replace(",", ""))
            continue

        # Followers count
        foll_match = re.search(r'(\d[\d,]*)\+?\s*followers?', segment, re.IGNORECASE)
        if foll_match:
            result["followers"] = int(foll_match.group(1).replace(",", ""))
            continue

        # Experience: "Experience: Company Name" or "Experience Company Name"
        exp_match = re.match(r'Experience:?\s*(.+)', segment, re.IGNORECASE)
        if exp_match:
            result["experience_text"] = exp_match.group(1).strip()
            continue

        # Education: "Education: School Name" or "Education School Name"
        edu_match = re.match(r'Education:?\s*(.+)', segment, re.IGNORECASE)
        if edu_match:
            result["education_text"] = edu_match.group(1).strip()
            continue

        # Location: explicit "Location: Place" prefix
        loc_match = re.match(r'Location:?\s*(.+)', segment, re.IGNORECASE)
        if loc_match:
            loc_val = loc_match.group(1).strip()
            # Truncate at LinkedIn boilerplate or sentence boundary
            loc_val = re.split(
                r'\.\s+(?:View|See|Connect|Join|Sign|Log|Learn)',
                loc_val,
            )[0].strip().rstrip(".")
            # Also truncate at any period followed by a capital letter (new sentence)
            loc_val = re.split(r'\.\s+[A-Z]', loc_val)[0].strip().rstrip(".")
            if loc_val:
                result["location"] = loc_val
            continue

        # Location: Usually a segment with geographic indicators (short segments only)
        if len(segment) < 60 and _looks_like_location(segment):
            result["location"] = segment
            continue

        # Skip very long segments (likely bio text, not structured metadata)
        if len(segment) > 100:
            continue

        # Headline: typically the first non-matched short segment
        if "headline" not in result and 3 < len(segment) < 80:
            result["headline"] = segment

    return result


def _looks_like_location(text: str) -> bool:
    """Check if a text segment looks like a geographic location."""
    # Must be short enough to be a location
    if len(text) > 60:
        return False

    location_indicators = [
        # Geographic features
        r"\b(?:Area|Bay|Metro|Greater|Region|County|Province|State)\b",
        # Common tech hub cities
        r"\b(?:California|New York|Texas|Florida|Washington|Massachusetts|"
        r"London|San Francisco|Seattle|Boston|Chicago|Los Angeles|Portland|"
        r"Austin|Denver|Atlanta|Miami|Phoenix|Minneapolis|Nashville|"
        r"Berlin|Paris|Amsterdam|Dublin|Stockholm|Zurich|Munich|"
        r"Toronto|Vancouver|Montreal|Ottawa|Calgary|"
        r"Sydney|Melbourne|Brisbane|Auckland|"
        r"Singapore|Hong Kong|Tokyo|Osaka|Seoul|Taipei|"
        r"Mumbai|Bangalore|Bengaluru|Delhi|Hyderabad|Pune|Chennai|"
        r"Beijing|Shanghai|Shenzhen|Guangzhou|"
        r"Tel Aviv|Dubai|Abu Dhabi|"
        r"Sao Paulo|Mexico City|Buenos Aires|Bogota|"
        r"Lagos|Nairobi|Cape Town|Johannesburg|Cairo)\b",
        # Country names
        r"\b(?:United States|United Kingdom|Canada|Australia|Germany|France|"
        r"India|China|Japan|Brazil|Israel|Nigeria|Kenya|South Africa)\b",
        # Country codes (standalone 2-3 letter codes with word boundaries)
        r"(?:^|\s)(?:US|USA|UK|UAE|CA|AU|DE|FR|IN|JP|BR|IL|SG|HK)(?:\s|$|,)",
    ]
    for pattern in location_indicators:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    # City, State/Country pattern: "San Francisco, CA" or "London, UK"
    # Use case-sensitive match to avoid "CEO, Shopify" false positive
    if re.search(r"[A-Z][a-z]{2,},\s*[A-Z]", text):
        return True

    return False


# ---------------------------------------------------------------------------
# Main scraper entry point (called by enricher.py)
# ---------------------------------------------------------------------------

async def scrape_linkedin(name: str, company: Optional[str] = None) -> Optional[LinkedInData]:
    """Search for and scrape any person's public LinkedIn profile.

    No API key needed. Uses DuckDuckGo to find the profile URL,
    then extracts data from the public page's meta tags, JSON-LD,
    and embedded <code> tags.
    """
    # Step 1: Find the LinkedIn profile URL (with snippet capture)
    linkedin_url, ddg_snippet = await _find_linkedin_url(name, company)
    if not linkedin_url:
        return None

    # Step 2: Fetch and parse the public profile
    raw_data = await _fetch_public_profile(linkedin_url)
    if not raw_data:
        # If we can't scrape the page but have a snippet, use that
        if ddg_snippet:
            parsed = _parse_linkedin_description(ddg_snippet)
            return LinkedInData(
                profile_url=linkedin_url,
                headline=parsed.get("headline"),
                location=parsed.get("location"),
                summary=ddg_snippet[:500] if ddg_snippet else None,
                connections=parsed.get("connections", 0),
            )
        return LinkedInData(profile_url=linkedin_url)

    # Step 3: Parse into structured data (with DDG snippet augmentation)
    return _parse_profile_data(raw_data, ddg_snippet)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
