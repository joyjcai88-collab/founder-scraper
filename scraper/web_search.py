"""Web search using Perplexity AI for sourced founder intelligence."""

from __future__ import annotations

import os
from typing import Optional

import httpx

from models.founder import WebSearchData
from scraper.safety import clean_scraped_text, sanitize_input

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


async def scrape_web_search(name: str, company: Optional[str] = None) -> Optional[WebSearchData]:
    """Query Perplexity AI for structured founder intelligence with citations."""
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        return None

    query = sanitize_input(name)
    if company:
        query += f" {sanitize_input(company)}"

    prompt = (
        f"Research the founder/CEO '{query}'. Provide a concise summary covering: "
        f"their background, previous companies, notable achievements, education, "
        f"fundraising history, and any public controversies. "
        f"Focus on facts relevant to evaluating them as a startup founder."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "sonar",
        "messages": [
            {
                "role": "system",
                "content": "You are a research assistant for a venture capital firm. "
                           "Provide factual, sourced information about founders and CEOs. "
                           "Be concise and stick to verifiable facts.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1024,
        "return_citations": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(PERPLEXITY_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Extract the response content
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return None

        # Clean and split into digestible snippets
        cleaned = clean_scraped_text(content)
        # Split by paragraphs or sentences for structured snippets
        paragraphs = [p.strip() for p in cleaned.split("\n") if p.strip() and len(p.strip()) > 20]
        if not paragraphs:
            paragraphs = [cleaned]

        # Extract citations/sources from the response
        sources = []
        citations = data.get("citations", [])
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, str):
                    sources.append(citation)
                elif isinstance(citation, dict):
                    url = citation.get("url", "")
                    if url:
                        sources.append(url)

        return WebSearchData(
            snippets=paragraphs[:15],
            sources=sources[:15],
        )

    except Exception:
        return None
