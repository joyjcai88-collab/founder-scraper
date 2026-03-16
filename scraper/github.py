"""GitHub public API scraper — no auth needed (60 req/hr unauthenticated)."""

from __future__ import annotations

import httpx

from models.founder import GitHubData
from scraper.safety import sanitize_input

API_BASE = "https://api.github.com"
TIMEOUT = 15


async def scrape_github(name: str, company: str | None = None) -> GitHubData | None:
    """Search GitHub for a user by name and return structured data."""
    query = sanitize_input(name)
    if company:
        query += f" {sanitize_input(company)}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Search for users matching the name
        search_resp = await client.get(
            f"{API_BASE}/search/users",
            params={"q": query, "per_page": 5},
            headers={"Accept": "application/vnd.github+json"},
        )
        if search_resp.status_code != 200:
            return None

        items = search_resp.json().get("items", [])
        if not items:
            return None

        # Take the top result
        user_login = items[0]["login"]
        profile_url = items[0]["html_url"]

        # Fetch full user profile
        user_resp = await client.get(
            f"{API_BASE}/users/{user_login}",
            headers={"Accept": "application/vnd.github+json"},
        )
        if user_resp.status_code != 200:
            return GitHubData(username=user_login, profile_url=profile_url)

        user = user_resp.json()

        # Fetch repos sorted by stars
        repos_resp = await client.get(
            f"{API_BASE}/users/{user_login}/repos",
            params={"sort": "stars", "direction": "desc", "per_page": 10},
            headers={"Accept": "application/vnd.github+json"},
        )
        repos = repos_resp.json() if repos_resp.status_code == 200 else []

        # Aggregate language and star data
        languages: dict[str, int] = {}
        total_stars = 0
        notable_repos = []

        for repo in repos:
            if isinstance(repo, dict):
                stars = repo.get("stargazers_count", 0)
                total_stars += stars
                lang = repo.get("language")
                if lang:
                    languages[lang] = languages.get(lang, 0) + 1
                if stars > 0:
                    notable_repos.append({
                        "name": repo.get("name", ""),
                        "stars": stars,
                        "description": (repo.get("description") or "")[:200],
                        "language": lang,
                    })

        top_languages = sorted(languages, key=languages.get, reverse=True)[:5]

        return GitHubData(
            username=user_login,
            profile_url=profile_url,
            bio=user.get("bio"),
            public_repos=user.get("public_repos", 0),
            followers=user.get("followers", 0),
            top_languages=top_languages,
            total_stars=total_stars,
            notable_repos=notable_repos[:5],
        )
