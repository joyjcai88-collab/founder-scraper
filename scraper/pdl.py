"""People Data Labs person enrichment API scraper.

Requires a PDL API key. Set PDL_API_KEY in your .env file.
Free tier: 100 requests/minute, billed per successful match only.

Sign up at https://www.peopledatalabs.com/ to get an API key.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

from models.founder import PDLData
from scraper.safety import clean_scraped_text, sanitize_input

API_URL = "https://api.peopledatalabs.com/v5/person/enrich"
TIMEOUT = 15
MIN_LIKELIHOOD = 4


async def scrape_pdl(name: str, company: Optional[str] = None) -> Optional[PDLData]:
    """Enrich a person via People Data Labs API."""
    api_key = os.environ.get("PDL_API_KEY")
    if not api_key:
        return None

    clean_name = sanitize_input(name)
    parts = clean_name.split(None, 1)
    if len(parts) < 2:
        return None

    first_name = parts[0]
    last_name = parts[1]

    params = {
        "first_name": first_name,
        "last_name": last_name,
        "min_likelihood": MIN_LIKELIHOOD,
        "titlecase": "true",
    }

    if company:
        params["company"] = sanitize_input(company)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(
            API_URL,
            params=params,
            headers={"X-API-Key": api_key},
        )

        if resp.status_code == 404:
            return None
        if resp.status_code == 402:
            return None  # out of credits
        if resp.status_code != 200:
            return None

        result = resp.json()
        data = result.get("data")
        if not data:
            return None

        likelihood = result.get("likelihood", 0)

        return _parse_response(data, likelihood)


def _parse_response(data: dict, likelihood: int) -> PDLData:
    """Parse PDL API response into our data model."""
    # LinkedIn URL
    linkedin_url = data.get("linkedin_url")

    # Headline / job title
    headline = data.get("job_title")
    if headline:
        headline = clean_scraped_text(headline)

    # Summary
    summary = data.get("summary")
    if summary:
        summary = clean_scraped_text(summary)

    # Location
    location_parts = []
    if data.get("locality"):
        location_parts.append(data["locality"])
    if data.get("region"):
        location_parts.append(data["region"])
    if data.get("country"):
        location_parts.append(data["country"])
    location = ", ".join(location_parts) if location_parts else None

    # Industry
    industry = data.get("industry")

    # Work experience
    experience = []
    for exp in (data.get("experience") or []):
        title = exp.get("title", {})
        if isinstance(title, dict):
            title = title.get("name", "")
        company_info = exp.get("company", {})
        company_name = ""
        if isinstance(company_info, dict):
            company_name = company_info.get("name", "")
        elif isinstance(company_info, str):
            company_name = company_info

        start_date = exp.get("start_date", "")
        end_date = exp.get("end_date", "present")
        is_primary = exp.get("is_primary", False)

        experience.append({
            "title": clean_scraped_text(str(title)),
            "company": clean_scraped_text(str(company_name)),
            "start_date": str(start_date or ""),
            "end_date": str(end_date or "present"),
            "is_primary": is_primary,
        })

    # Sort: primary first, then by start date descending
    experience.sort(key=lambda x: (not x.get("is_primary"), x.get("start_date", "")), reverse=False)

    # Education
    education = []
    for edu in (data.get("education") or []):
        school_info = edu.get("school", {})
        school_name = ""
        if isinstance(school_info, dict):
            school_name = school_info.get("name", "")
        elif isinstance(school_info, str):
            school_name = school_info

        degree = ""
        degrees = edu.get("degrees", [])
        if degrees:
            degree = degrees[0] if isinstance(degrees[0], str) else ""

        majors = edu.get("majors", [])
        major = majors[0] if majors and isinstance(majors[0], str) else ""

        education.append({
            "school": clean_scraped_text(str(school_name)),
            "degree": clean_scraped_text(str(degree)),
            "major": clean_scraped_text(str(major)),
        })

    # Skills
    skills = []
    for skill in (data.get("skills") or []):
        if isinstance(skill, str):
            skills.append(skill)
        elif isinstance(skill, dict):
            skills.append(skill.get("name", ""))

    # Social profiles
    social_profiles = []
    if linkedin_url:
        social_profiles.append(linkedin_url)
    if data.get("twitter_url"):
        social_profiles.append(data["twitter_url"])
    if data.get("github_url"):
        social_profiles.append(data["github_url"])
    if data.get("facebook_url"):
        social_profiles.append(data["facebook_url"])

    return PDLData(
        linkedin_url=linkedin_url,
        headline=headline,
        summary=summary,
        location=location,
        industry=industry,
        experience=experience[:10],
        education=education[:5],
        skills=skills[:20],
        social_profiles=social_profiles,
        likelihood=likelihood,
    )
