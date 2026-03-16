"""Enricher: orchestrates all scrapers concurrently and merges results."""

from __future__ import annotations

import asyncio

from models.founder import FounderProfile
from scraper.crunchbase import scrape_crunchbase
from scraper.github import scrape_github
from scraper.twitter import scrape_twitter
from scraper.web_search import scrape_web_search


async def enrich_founder(name: str, company: str | None = None) -> FounderProfile:
    """Run all scrapers concurrently and merge into a unified FounderProfile."""
    github_task = asyncio.create_task(_safe_scrape(scrape_github, name, company))
    crunchbase_task = asyncio.create_task(_safe_scrape(scrape_crunchbase, name, company))
    twitter_task = asyncio.create_task(_safe_scrape(scrape_twitter, name, company))
    web_task = asyncio.create_task(_safe_scrape(scrape_web_search, name, company))

    github_data, crunchbase_data, twitter_data, web_data = await asyncio.gather(
        github_task, crunchbase_task, twitter_task, web_task
    )

    # Try to infer company from scraped data if not provided
    inferred_company = company
    if not inferred_company and crunchbase_data:
        inferred_company = crunchbase_data.company_name

    # Collect source links
    profile = FounderProfile(
        name=name,
        company=inferred_company,
        github=github_data,
        crunchbase=crunchbase_data,
        twitter=twitter_data,
        web_search=web_data,
    )

    return profile


async def _safe_scrape(scraper_fn, name: str, company: str | None):
    """Run a scraper with error handling — never let one failure kill the pipeline."""
    try:
        return await scraper_fn(name, company)
    except Exception:
        return None
