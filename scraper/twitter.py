"""Twitter/X public profile scraper."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from models.founder import TwitterData
from scraper.safety import clean_scraped_text, is_safe_url, sanitize_input

TIMEOUT = 15

# Nitter instances as fallback for scraping public Twitter profiles
# These render Twitter profiles as static HTML
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]


async def scrape_twitter(name: str, company: str | None = None) -> TwitterData | None:
    """Search for and scrape a public Twitter/X profile."""
    query = sanitize_input(name)

    # First, try to find the Twitter handle via DuckDuckGo
    handle = await _find_twitter_handle(query, company)
    if not handle:
        return None

    # Try scraping via Nitter instances (static HTML rendering of Twitter)
    for instance in NITTER_INSTANCES:
        result = await _scrape_nitter(instance, handle)
        if result:
            return result

    return TwitterData(username=handle, profile_url=f"https://x.com/{handle}")


async def _find_twitter_handle(name: str, company: str | None) -> str | None:
    """Use DuckDuckGo to find a person's Twitter handle."""
    search_query = f"{name} twitter.com"
    if company:
        search_query += f" {sanitize_input(company)}"

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": search_query},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            },
        )
        if resp.status_code != 200:
            return None

        # Look for twitter.com or x.com profile URLs in results
        pattern = r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,15})(?:\?|/|$)"
        matches = re.findall(pattern, resp.text)

        # Filter out common non-profile paths
        skip = {"search", "intent", "share", "hashtag", "i", "home", "explore", "settings", "login"}
        for match in matches:
            if match.lower() not in skip:
                return match

    return None


async def _scrape_nitter(instance_url: str, handle: str) -> TwitterData | None:
    """Scrape a Twitter profile via a Nitter instance."""
    url = f"{instance_url}/{handle}"
    if not is_safe_url(url):
        return None

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return None

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract bio
        bio_el = soup.select_one(".profile-bio")
        bio = clean_scraped_text(bio_el.get_text(strip=True)) if bio_el else None

        # Extract stats
        followers = _parse_stat(soup, "followers")
        following = _parse_stat(soup, "following")
        post_count = _parse_stat(soup, "posts") or _parse_stat(soup, "tweets")

        # Extract recent post topics (from timeline text)
        recent_topics: list[str] = []
        for tweet_el in soup.select(".timeline-item .tweet-content")[:5]:
            text = clean_scraped_text(tweet_el.get_text(strip=True))
            if text and len(text) > 10:
                recent_topics.append(text[:200])

        return TwitterData(
            username=handle,
            profile_url=f"https://x.com/{handle}",
            bio=bio,
            followers=followers,
            following=following,
            post_count=post_count,
            recent_topics=recent_topics[:5],
        )


def _parse_stat(soup: BeautifulSoup, stat_name: str) -> int:
    """Extract a numeric stat from a Nitter profile page."""
    for el in soup.select(".profile-stat"):
        label = el.get_text(strip=True).lower()
        if stat_name in label:
            num_el = el.select_one(".profile-stat-num")
            if num_el:
                text = num_el.get_text(strip=True).replace(",", "").replace(".", "")
                try:
                    # Handle abbreviated numbers like "1.2K"
                    if text.upper().endswith("K"):
                        return int(float(text[:-1]) * 1_000)
                    elif text.upper().endswith("M"):
                        return int(float(text[:-1]) * 1_000_000)
                    return int(text)
                except ValueError:
                    return 0
    return 0
