"""Web search scraper using DuckDuckGo for supplementary founder info."""

from __future__ import annotations

from duckduckgo_search import DDGS

from models.founder import WebSearchData
from scraper.safety import clean_scraped_text, sanitize_input


async def scrape_web_search(name: str, company: str | None = None) -> WebSearchData | None:
    """Search DuckDuckGo for additional context about a founder."""
    query = sanitize_input(name)
    if company:
        query += f" {sanitize_input(company)}"

    queries = [
        f"{query} founder CEO startup",
        f"{query} interview biography background",
    ]

    snippets: list[str] = []
    sources: list[str] = []

    for search_query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(search_query, max_results=5))

            for result in results:
                body = result.get("body", "")
                href = result.get("href", "")
                title = result.get("title", "")

                if body:
                    cleaned = clean_scraped_text(f"{title}: {body}")
                    if cleaned and len(cleaned) > 20:
                        snippets.append(cleaned)

                if href:
                    sources.append(href)

        except Exception:
            continue

    if not snippets:
        return None

    return WebSearchData(
        snippets=snippets[:15],
        sources=sources[:15],
    )
