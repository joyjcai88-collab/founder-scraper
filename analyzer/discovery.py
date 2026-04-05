"""Discovery engine: find founders by company criteria using Perplexity AI."""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

import httpx

from scraper.safety import sanitize_input

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


async def discover_founders(
    industry: str,
    stage: Optional[str] = None,
    product: Optional[str] = None,
    date_founded: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, str]]:
    """Search for founders matching company criteria via Perplexity AI.

    Returns a list of dicts: [{"name": "...", "company": "...", "role": "..."}]
    """
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        return []

    # Build a natural language query from the filters
    parts = [f"in the {sanitize_input(industry)} industry"]
    if stage:
        parts.append(f"at {sanitize_input(stage)} stage")
    if product:
        parts.append(f"building {sanitize_input(product)} products")
    if date_founded:
        parts.append(f"founded {sanitize_input(date_founded)}")

    criteria = ", ".join(parts)

    prompt = (
        f"Find {limit} startup founders/CEOs {criteria}. "
        f"For each founder, provide their full name, company name, and title/role. "
        f"Focus on real, verifiable founders of active startups. "
        f"Return ONLY a JSON array with objects containing: "
        f'"name" (full name), "company" (company name), "role" (their title). '
        f"No markdown, no explanation — just the JSON array."
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
                "content": (
                    "You are a startup research assistant. Return ONLY valid JSON arrays "
                    "when asked for founder lists. No markdown code fences, no explanation. "
                    "Each object must have: name, company, role."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048,
        "return_citations": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                PERPLEXITY_API_URL, headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        if not content:
            return []

        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        founders = json.loads(content)
        if not isinstance(founders, list):
            return []

        # Validate and clean each entry
        results = []
        for f in founders[:limit]:
            if isinstance(f, dict) and f.get("name"):
                results.append({
                    "name": str(f.get("name", "")),
                    "company": str(f.get("company", "")),
                    "role": str(f.get("role", "")),
                })

        return results

    except (json.JSONDecodeError, httpx.HTTPError, KeyError):
        return []
