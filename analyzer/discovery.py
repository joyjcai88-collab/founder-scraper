"""Multi-source founder discovery engine.

Searches across 10+ founder sources via DuckDuckGo (ddgs package).
No API keys needed — all searches are free.

Sources searched:
- Y Combinator company directory
- LinkedIn profiles
- Crunchbase person/company pages
- Twitter/X founder profiles
- Product Hunt maker profiles
- AngelList / Wellfound profiles
- On Deck fellowship alumni
- Entrepreneur First alumni
- Techstars alumni
- Substack founder newsletters
- Buildspace alumni
- Pioneer.app founders
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from scraper.safety import sanitize_input

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """A founder discovery source with site-specific search and parsing."""
    key: str
    label: str
    site_query: str  # DuckDuckGo site: filter or keyword prefix
    extra_keywords: str  # Additional keywords to append
    url_pattern: str  # Regex to match valid result URLs
    parser: str  # Which parser to use: 'linkedin', 'generic', 'yc', 'crunchbase'


SOURCES: List[Source] = [
    # --- Accelerators & Cohorts ---
    Source(
        key="yc",
        label="Y Combinator",
        site_query="site:ycombinator.com/companies",
        extra_keywords="",
        url_pattern=r"ycombinator\.com/companies/",
        parser="yc",
    ),
    Source(
        key="techstars",
        label="Techstars",
        site_query="site:techstars.com",
        extra_keywords="founder CEO portfolio",
        url_pattern=r"techstars\.com",
        parser="generic",
    ),
    # --- Social Platforms ---
    Source(
        key="linkedin",
        label="LinkedIn",
        site_query="site:linkedin.com/in",
        extra_keywords="founder OR CEO OR co-founder",
        url_pattern=r"linkedin\.com/in/",
        parser="linkedin",
    ),
    Source(
        key="twitter",
        label="Twitter/X",
        site_query="site:twitter.com OR site:x.com",
        extra_keywords="founder CEO building",
        url_pattern=r"(twitter\.com|x\.com)/\w+",
        parser="twitter",
    ),
    Source(
        key="substack",
        label="Substack",
        site_query="site:substack.com",
        extra_keywords="founder CEO startup",
        url_pattern=r"substack\.com",
        parser="generic",
    ),
    # --- Deal Flow Databases ---
    Source(
        key="crunchbase",
        label="Crunchbase",
        site_query="site:crunchbase.com/person",
        extra_keywords="founder",
        url_pattern=r"crunchbase\.com/person/",
        parser="crunchbase",
    ),
    Source(
        key="wellfound",
        label="AngelList / Wellfound",
        site_query="site:wellfound.com OR site:angel.co",
        extra_keywords="founder",
        url_pattern=r"(wellfound\.com|angel\.co)",
        parser="generic",
    ),
    Source(
        key="producthunt",
        label="Product Hunt",
        site_query="site:producthunt.com",
        extra_keywords="maker founder launched",
        url_pattern=r"producthunt\.com",
        parser="generic",
    ),
    # --- Communities & Fellowships ---
    Source(
        key="ondeck",
        label="On Deck",
        site_query="site:beondeck.com OR \"On Deck fellowship\"",
        extra_keywords="founder",
        url_pattern=r"(beondeck\.com|ondeck)",
        parser="generic",
    ),
    Source(
        key="ef",
        label="Entrepreneur First",
        site_query="site:joinef.com OR \"Entrepreneur First\"",
        extra_keywords="founder cohort",
        url_pattern=r"(joinef\.com|entrepreneur first)",
        parser="generic",
    ),
    Source(
        key="buildspace",
        label="Buildspace",
        site_query="site:buildspace.so OR \"buildspace\"",
        extra_keywords="founder builder",
        url_pattern=r"buildspace",
        parser="generic",
    ),
    Source(
        key="pioneer",
        label="Pioneer.app",
        site_query="site:pioneer.app",
        extra_keywords="founder",
        url_pattern=r"pioneer\.app",
        parser="generic",
    ),
]

# Default sources to search (high-signal ones)
DEFAULT_SOURCES = ["yc", "linkedin", "crunchbase", "twitter", "wellfound", "producthunt"]

SOURCE_MAP: Dict[str, Source] = {s.key: s for s in SOURCES}


# ---------------------------------------------------------------------------
# LinkedIn industry taxonomy — grouped into VC-relevant buckets
# ---------------------------------------------------------------------------

LINKEDIN_INDUSTRY_BUCKETS: Dict[str, List[str]] = {
    "Technology & Software": [
        "Software Development", "Technology, Information and Internet",
        "IT Services and IT Consulting", "Computer Hardware Manufacturing",
        "Semiconductor Manufacturing", "Computer Networking Products",
    ],
    "AI & Deep Tech": [
        "Artificial Intelligence", "Machine Learning", "Data Analytics",
        "Robotics", "Quantum Computing", "Augmented and Virtual Reality",
    ],
    "Cybersecurity & Infrastructure": [
        "Computer and Network Security", "Cloud Computing",
        "Mobile Computing", "Internet of Things", "Embedded Software",
    ],
    "Fintech & Financial Services": [
        "Financial Services", "Banking", "Insurance", "Investment Management",
        "Venture Capital and Private Equity", "Credit Intermediation",
    ],
    "Crypto & Web3": [
        "Cryptocurrency", "Blockchain and Cryptocurrency", "Decentralized Finance",
        "NFT and Digital Assets", "Web3",
    ],
    "Healthcare & Life Sciences": [
        "Hospitals and Health Care", "Biotechnology Research",
        "Pharmaceutical Manufacturing", "Medical Device",
        "Mental Health Care", "Wellness and Fitness Services",
    ],
    "Consumer & E-Commerce": [
        "E-Commerce and Online Retail", "Retail", "Consumer Goods",
        "Food and Beverage Services", "Personal Care Product Manufacturing",
        "Apparel and Fashion",
    ],
    "Media & Entertainment": [
        "Entertainment Providers", "Media Production", "Online Audio and Video Media",
        "Gaming", "Advertising Services", "Book and Periodical Publishing",
    ],
    "Education & Future of Work": [
        "Education Administration Programs", "E-Learning Providers",
        "Human Resources Services", "Staffing and Recruiting",
        "Professional Training and Coaching",
    ],
    "Industrial & Manufacturing": [
        "Manufacturing", "Automation Machinery Manufacturing",
        "Motor Vehicle Manufacturing", "Aerospace and Defense",
        "Electrical Equipment Manufacturing",
    ],
    "Energy & Climate": [
        "Renewable Energy Semiconductor Manufacturing", "Solar Electric Power Generation",
        "Wind Electric Power Generation", "Electric Power Generation",
        "Environmental Services", "Waste Treatment and Disposal",
    ],
    "Real Estate & Construction": [
        "Real Estate", "Real Estate and Equipment Rental Services",
        "Construction", "Architecture and Planning", "Property Management",
    ],
    "Transportation & Logistics": [
        "Transportation, Logistics, Supply Chain and Storage",
        "Truck Transportation", "Maritime Transportation",
        "Freight and Package Transportation", "Ground Passenger Transportation",
    ],
    "Agriculture & Food Tech": [
        "Farming", "Agricultural Chemical Manufacturing",
        "Food and Beverage Manufacturing", "Food and Beverage Retail",
        "Alternative Protein", "Precision Agriculture",
    ],
    "Professional & Legal Services": [
        "Law Practice", "Legal Services", "Management Consulting",
        "Accounting", "Market Research", "Public Relations and Communications Services",
    ],
    "Government & Non-Profit": [
        "Government Administration", "Public Policy Offices",
        "Non-profit Organizations", "Think Tanks", "Civic and Social Organizations",
    ],
    "Space & Defense": [
        "Defense and Space Manufacturing", "Nanotechnology Research",
        "Nuclear Electric Power Generation", "Satellite Telecommunications",
        "Weapons and Ammunition Manufacturing",
    ],
    "Hospitality & Travel": [
        "Hospitality", "Hotels and Motels", "Travel Arrangements",
        "Restaurants", "Recreational Facilities",
    ],
}


async def discover_all_linkedin_industries(
    founders_per_bucket: int = 3,
) -> List[Dict[str, str]]:
    """Discover founders across every LinkedIn industry category bucket.

    Runs one Claude Haiku call per bucket concurrently, then deduplicates.
    Returns a stream-friendly list ordered by bucket.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    async def _bucket_founders(bucket_name: str, industries: List[str]) -> List[Dict[str, str]]:
        industry_list = ", ".join(industries)
        prompt = (
            f"List {founders_per_bucket * 2} real, publicly known startup founders "
            f"from these LinkedIn industry categories: {industry_list}.\n\n"
            f"Return ONLY a valid JSON array — no markdown, no explanation:\n"
            f'[{{"name": "Full Name", "company": "Company Name", "role": "Founder/CEO/CTO", '
            f'"industry": "Specific Industry", "product_desc": "One sentence on what they build"}}]\n\n'
            f"Rules: real people only, each with name + company, varied across the listed industries."
        )
        try:
            resp = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            text = next((b.text for b in resp.content if b.type == "text"), "").strip()
            match = re.search(r'\[[\s\S]*\]', text)
            if not match:
                return []
            raw = json.loads(match.group(0))
            results = []
            for f in raw:
                name = (f.get("name") or "").strip()
                company = (f.get("company") or "").strip()
                if not name or not company:
                    continue
                results.append({
                    "name": name,
                    "company": company,
                    "role": f.get("role") or "Founder",
                    "product_desc": f.get("product_desc") or "",
                    "source": f"LinkedIn – {f.get('industry', bucket_name)}",
                    "url": "",
                    "_bucket": bucket_name,
                })
            print(f"[discovery] Bucket '{bucket_name}': {len(results)} founders", flush=True)
            return results[:founders_per_bucket]
        except Exception as exc:
            print(f"[discovery] Bucket '{bucket_name}' failed: {exc}", flush=True)
            return []

    # Run all buckets concurrently
    tasks = [_bucket_founders(name, industries) for name, industries in LINKEDIN_INDUSTRY_BUCKETS.items()]
    bucket_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge and deduplicate
    all_results = []
    seen_names: set = set()
    for res in bucket_results:
        if isinstance(res, Exception):
            continue
        for entry in res:
            key = entry["name"].lower().strip()
            if key not in seen_names and len(key) >= 3:
                seen_names.add(key)
                all_results.append(entry)

    return all_results


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------

async def _claude_seed_founders(
    industry: str,
    stage: Optional[str],
    product: Optional[str],
    date_founded: Optional[str],
    limit: int,
) -> List[Dict[str, str]]:
    """Use Claude Haiku to generate a seeded list of real founders matching criteria.

    This is fast (~1-2s), reliable for niche industries (crypto, fintech, biotech, etc.),
    and supplements the web-search results which can be sparse for specific domains.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    import anthropic

    criteria_lines = []
    if industry:      criteria_lines.append(f"Industry/sector: {industry}")
    if stage:         criteria_lines.append(f"Funding stage: {stage}")
    if product:       criteria_lines.append(f"Product type: {product}")
    if date_founded:  criteria_lines.append(f"Founded: {date_founded}")
    criteria_str = "\n".join(criteria_lines) if criteria_lines else "any startup"

    prompt = f"""List {min(limit * 2, 20)} real, publicly known startup founders that match ALL of the following criteria:
{criteria_str}

Return ONLY a valid JSON array — no markdown, no explanation, no code fences — just the raw JSON:
[{{"name": "Full Name", "company": "Company Name", "role": "Founder/CEO/CTO", "product_desc": "One sentence on what they build"}}]

Rules:
- Only include real people with verifiable public presence
- Each entry must have both a name and a company
- Prefer founders who have raised funding or have notable public profiles
- Vary the list — don't cluster around only the most famous names"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()

        # Extract JSON array (handle any surrounding whitespace or stray text)
        match = re.search(r'\[[\s\S]*\]', text)
        if not match:
            return []

        raw = json.loads(match.group(0))
        results = []
        seen = set()
        for f in raw:
            name = (f.get("name") or "").strip()
            company = (f.get("company") or "").strip()
            if not name or not company:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "name": name,
                "company": company,
                "role": f.get("role") or "Founder",
                "product_desc": f.get("product_desc") or "",
                "source": "AI-discovered",
                "url": "",
            })
        return results[:limit]
    except Exception as exc:
        print(f"[discovery] Claude seed failed: {exc}", flush=True)
        return []


async def discover_founders(
    industry: str,
    stage: Optional[str] = None,
    product: Optional[str] = None,
    date_founded: Optional[str] = None,
    limit: int = 10,
    sources: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Search multiple sources for founders matching company criteria.

    Returns a list of dicts:
        [{"name": "...", "company": "...", "role": "...", "source": "...", "url": "..."}]
    """
    active_sources = [SOURCE_MAP[s] for s in (sources or DEFAULT_SOURCES) if s in SOURCE_MAP]
    if not active_sources:
        active_sources = [SOURCE_MAP[s] for s in DEFAULT_SOURCES]

    # Build search criteria — separate core terms from stage/date modifiers.
    # Stage terms (e.g. "Pre-seed", "Series A") rarely appear on profile pages,
    # so they shouldn't be required in site-restricted queries. Instead, we use
    # them only in open-web fallback queries and for result filtering.
    core_parts = []
    if industry:
        core_parts.append(sanitize_input(industry))
    if product:
        core_parts.append(sanitize_input(product))
    if not core_parts:
        core_parts.append("startup")
    core_criteria = " ".join(core_parts)

    # Stage and date are "soft" modifiers — used in fallback queries only
    stage_term = sanitize_input(stage) if stage else ""
    date_term = f"founded {sanitize_input(date_founded)}" if date_founded else ""

    # Search each source and collect results
    all_results: List[Dict[str, str]] = []
    seen_names: set = set()

    import asyncio
    from scraper.multi_search import multi_search

    # Calculate results per source to balance coverage
    per_source = max(5, (limit * 3) // len(active_sources))

    async def _search_source(source: Source) -> List[Dict[str, str]]:
        """Search a single source with primary + fallback queries."""
        query = f"{source.site_query} {core_criteria}"
        if source.extra_keywords:
            query += f" {source.extra_keywords}"

        raw = await multi_search(query, max_results=per_source)

        # If site-restricted query returned nothing, try open-web fallback
        if not raw:
            fallback_parts = [core_criteria]
            if stage_term:
                fallback_parts.append(stage_term)
            if date_term:
                fallback_parts.append(date_term)
            fallback_parts.append(source.label)
            fallback_parts.append("founder")
            fallback_query = " ".join(fallback_parts)

            raw = await multi_search(fallback_query, max_results=per_source)

        print(f"[discovery] Source {source.key}: query={query[:80]!r} → {len(raw)} raw results", flush=True)
        return raw

    # Run Claude seed + all web sources concurrently
    claude_task = asyncio.create_task(_claude_seed_founders(
        industry or "", stage, product, date_founded, limit
    ))
    web_tasks = [_search_source(src) for src in active_sources]
    all_tasks_results = await asyncio.gather(claude_task, *web_tasks, return_exceptions=True)

    claude_results = all_tasks_results[0] if not isinstance(all_tasks_results[0], Exception) else []
    web_task_results = all_tasks_results[1:]

    # Add Claude-seeded founders first (highest signal)
    for entry in claude_results:
        name_key = entry["name"].lower().strip()
        if name_key not in seen_names and len(name_key) >= 3:
            seen_names.add(name_key)
            all_results.append(entry)
            print(f"[discovery] SEEDED: {entry['name']} @ {entry.get('company', '?')}", flush=True)

    # Collect web search results
    source_results: List[tuple] = []  # [(source, results), ...]
    for source, raw_results in zip(active_sources, web_task_results):
        if isinstance(raw_results, Exception):
            print(f"[discovery] Source {source.key} failed: {raw_results}", flush=True)
            continue
        source_results.append((source, raw_results))

    # --- Process all results ---
    for source, raw_results in source_results:
        for item in raw_results:
            if len(all_results) >= limit:
                break

            href = item.get("href", "")
            title = item.get("title", "")
            body = item.get("body", "")

            # Validate URL matches the source pattern
            if not re.search(source.url_pattern, href, re.IGNORECASE):
                print(f"[discovery] SKIP url mismatch: {href[:80]}", flush=True)
                continue

            # Parse based on source type
            if source.parser == "linkedin":
                parsed = _parse_linkedin(href, title, body)
            elif source.parser == "yc":
                parsed = _parse_yc(href, title, body)
            elif source.parser == "crunchbase":
                parsed = _parse_crunchbase(href, title, body)
            elif source.parser == "twitter":
                parsed = _parse_twitter(href, title, body)
            else:
                parsed = _parse_generic(href, title, body)

            if not parsed or not parsed.get("name"):
                print(f"[discovery] SKIP no name parsed from: {title[:60]}", flush=True)
                continue

            # Only keep results with real person names
            if not _looks_like_person_name(parsed["name"]):
                print(f"[discovery] SKIP not a person name: {parsed['name']!r}", flush=True)
                continue

            # Try to fill in company if missing
            company = (parsed.get("company") or "").strip()
            if not company or len(company) < 2:
                company = _extract_company_from_text(body)
                if company:
                    parsed["company"] = company

            # Try to fill in product_desc if missing
            product_desc = (parsed.get("product_desc") or "").strip()
            if not product_desc:
                product_desc = _extract_product(body)
                if product_desc:
                    parsed["product_desc"] = product_desc

            # Must have BOTH a founder name AND at least a company or product
            has_company = bool((parsed.get("company") or "").strip())
            has_product = bool((parsed.get("product_desc") or "").strip())
            if not has_company and not has_product:
                print(f"[discovery] SKIP no company or product: {parsed['name']}", flush=True)
                continue

            # Deduplicate by normalized name
            name_key = parsed["name"].lower().strip()
            if name_key in seen_names or len(name_key) < 3:
                continue
            seen_names.add(name_key)

            parsed["source"] = source.label
            parsed["url"] = href
            all_results.append(parsed)
            print(f"[discovery] FOUND: {parsed['name']} @ {parsed.get('company', '?')} [{source.key}]", flush=True)

    return all_results


def get_available_sources() -> List[Dict[str, str]]:
    """Return list of available sources with key and label."""
    return [{"key": s.key, "label": s.label} for s in SOURCES]


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

# Words that indicate a source/company/page title, not a person
_NOT_A_PERSON = {
    "twitter", "linkedin", "crunchbase", "facebook", "instagram", "github",
    "product hunt", "producthunt", "angellist", "wellfound", "techstars",
    "y combinator", "on deck", "buildspace", "pioneer", "substack",
    "entrepreneur first", "medium", "startups", "companies", "funded",
    "series", "seed", "pre-seed",
}

# Job titles that get mistaken for names
_TITLE_WORDS = {
    "senior", "junior", "lead", "staff", "principal", "director", "manager",
    "engineer", "developer", "designer", "analyst", "consultant", "product",
    "marketing", "sales", "operations", "head", "vp", "vice", "president",
    "associate", "intern", "specialist", "coordinator", "executive",
}


def _looks_like_person_name(name: str) -> bool:
    """Check if a string looks like a real person's name."""
    if not name or len(name) < 3:
        return False
    # Too long for a name
    if len(name) > 40:
        return False
    # Must have at least 2 words (first + last name)
    words = name.split()
    if len(words) < 2:
        return False
    # Too many words — likely a title or sentence
    if len(words) > 5:
        return False
    # Check against known non-person words
    lower = name.lower()
    for bad in _NOT_A_PERSON:
        if bad == lower or lower.startswith(bad + " ") or lower.endswith(" " + bad):
            return False
    # Should not contain special chars that indicate a title/URL
    if any(c in name for c in ["http", "www.", ".com", "@", "#", "(", ")", "|"]):
        return False
    # Each word should start with a letter (person names do)
    for word in words:
        if not word[0].isalpha():
            return False
    # Reject names starting with prepositions or articles — fragments, not names
    first_word = words[0].lower().rstrip(".,")
    if first_word in {"of", "at", "in", "on", "for", "by", "from", "with",
                       "the", "a", "an", "to", "and", "or", "is", "was"}:
        return False
    # Reject job titles mistaken for names
    if first_word in _TITLE_WORDS:
        return False
    # Real names have capitalized words (at least first and last)
    capitalized = sum(1 for w in words if w[0].isupper())
    if capitalized < 2:
        return False
    # Reject if any word is a common non-name word
    lower_words = {w.lower().rstrip(".,") for w in words}
    non_name = {"the", "for", "and", "with", "how", "why", "what", "top",
                "best", "new", "app", "tool", "tools", "platform", "powering",
                "makers", "devops", "software", "startup", "startups",
                "digital", "global", "review", "list", "guide", "free",
                "nvidia", "google", "amazon", "meta", "apple", "microsoft"}
    if lower_words & non_name:
        return False
    return True


# ---------------------------------------------------------------------------
# Source-specific parsers
# ---------------------------------------------------------------------------

def _extract_product(body: str) -> str:
    """Try to extract a short product/service description from a search snippet."""
    if not body:
        return ""
    # Look for common patterns describing what the company/person does
    patterns = [
        r"(?:building|builds?|created?|developing|offers?|provides?|making)\s+(.{10,80}?)(?:\.|,|$)",
        r"(?:platform|tool|app|service|product|solution|software)\s+(?:for|that)\s+(.{10,80}?)(?:\.|,|$)",
        r"(?:helps?|enabling|empowering)\s+(.{10,80}?)(?:\.|,|$)",
    ]
    for pat in patterns:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            desc = m.group(1).strip()
            # Clean up and cap length
            desc = re.sub(r"\s+", " ", desc).strip().rstrip(".,;")
            if len(desc) > 80:
                desc = desc[:77] + "..."
            return desc
    # Fallback: use first sentence of body if short enough
    first = body.split(".")[0].strip()
    if 15 < len(first) < 100:
        return first
    return ""


_COMPANY_STOP = r"(?:\.|,|\s{2}|\||\bin\b|\bbased\b|\bto\b|\bon\b|\band\b|\bfor\b|\bwith\b|\bsince\b|$)"


def _extract_company_from_text(text: str) -> str:
    """Try to extract a company name from body/snippet text as a fallback."""
    if not text:
        return ""
    # Pattern: "Founder of CompanyName" / "CEO of CompanyName" (highest signal)
    of_match = re.search(
        r"(?:founder|co-founder|CEO|CTO|COO)\s+(?:of|at)\s+([A-Z][a-zA-Z0-9][\w\s&.]{0,30}?)" + _COMPANY_STOP,
        text, re.IGNORECASE,
    )
    if of_match:
        return of_match.group(1).strip().rstrip(".,; ")

    # Pattern: "at CompanyName" or "@ CompanyName"
    at_match = re.search(
        r"(?:^|\s)(?:at|@)\s+([A-Z][a-zA-Z0-9][\w\s&.]{0,30}?)" + _COMPANY_STOP,
        text,
    )
    if at_match:
        return at_match.group(1).strip().rstrip(".,; ")

    # Pattern: "building CompanyName" or "launched CompanyName"
    build_match = re.search(
        r"(?:building|launched|runs?|leads?)\s+([A-Z][a-zA-Z0-9][\w\s&.]{0,30}?)" + _COMPANY_STOP,
        text, re.IGNORECASE,
    )
    if build_match:
        return build_match.group(1).strip().rstrip(".,; ")

    return ""


def _parse_linkedin(href: str, title: str, body: str = "") -> Optional[Dict[str, str]]:
    """Parse a LinkedIn search result."""
    # Filter out non-profile URLs
    slug_match = re.search(r"linkedin\.com/in/([a-zA-Z0-9_-]+)", href)
    if not slug_match:
        return None
    slug = slug_match.group(1)
    if slug in ("login", "signup", "feed", "pulse"):
        return None

    # Remove " | LinkedIn" suffix
    title = re.sub(r"\s*[\|·\-]\s*LinkedIn\s*$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s*\.{3,}\s*", " ", title).strip()

    name = ""
    role = ""
    company = ""

    parts = [p.strip() for p in title.split(" - ") if p.strip()]

    if len(parts) >= 3:
        name, role, company = parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        name = parts[0]
        second = parts[1]
        at_match = re.match(r"(.+?)\s+(?:at|@)\s+(.+)", second, re.IGNORECASE)
        pipe_match = re.match(r"(.+?)\s*\|\s*(.+)", second)
        if at_match:
            role, company = at_match.group(1).strip(), at_match.group(2).strip()
        elif pipe_match:
            role, company = pipe_match.group(1).strip(), pipe_match.group(2).strip()
        else:
            role = second
    elif len(parts) == 1:
        name = parts[0]

    name = re.sub(r"\s+", " ", name).strip()
    role = re.sub(r"\s+", " ", role).strip()
    company = re.sub(r"\s+", " ", company).strip()

    # Clean up company — extract just the company name from long headlines
    # e.g. "Coinscrap Finance | LinkedIn Top Voice | Reshaping Fintech" → "Coinscrap Finance"
    if company and "|" in company:
        company = company.split("|")[0].strip()
    # Truncate overly long company strings (likely a headline, not a company)
    if len(company) > 40:
        # Try to extract the core company name
        co_match = re.match(r"([A-Z][a-zA-Z0-9\s&.]+?)(?:\s*[|,\-·]|\s+(?:Inc|LLC|Ltd|Corp))", company)
        if co_match:
            company = co_match.group(1).strip()
        else:
            company = company[:40].rsplit(" ", 1)[0].strip()

    # If no company from title, try to extract from body
    if not company and body:
        company = _extract_company_from_text(body)

    return {"name": name, "company": company, "role": role or "Founder", "product_desc": _extract_product(body)}


def _parse_yc(href: str, title: str, body: str) -> Optional[Dict[str, str]]:
    """Parse a Y Combinator company directory result."""
    # YC URLs look like: ycombinator.com/companies/company-name
    slug_match = re.search(r"ycombinator\.com/companies/([a-zA-Z0-9_-]+)", href)
    if not slug_match:
        return None

    # Title format: "Company Name | Y Combinator" or "Company Name"
    company = re.sub(r"\s*[\|·\-]\s*Y\s*Combinator\s*$", "", title, flags=re.IGNORECASE).strip()
    company = re.sub(r"\s*\(.*?\)\s*$", "", company).strip()

    # Try to extract founder name from body/snippet
    name = ""
    role = "Founder"

    # Body often contains: "Company description. Founded by Name1, Name2."
    founder_match = re.search(
        r"(?:founded by|co-founded by|founder[s]?:?)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)",
        body, re.IGNORECASE
    )
    if founder_match:
        name = founder_match.group(1).strip()
        # Take just the first founder if multiple
        if "," in name:
            name = name.split(",")[0].strip()
        if " and " in name.lower():
            name = name.split(" and ")[0].strip()

    # Skip if we couldn't extract an actual founder name
    if not name:
        return None

    return {"name": name, "company": company, "role": role, "product_desc": _extract_product(body)}


def _parse_crunchbase(href: str, title: str, body: str) -> Optional[Dict[str, str]]:
    """Parse a Crunchbase person page result."""
    # URL: crunchbase.com/person/first-last
    slug_match = re.search(r"crunchbase\.com/person/([a-zA-Z0-9_-]+)", href)
    if not slug_match:
        return None

    # Title formats from DDG:
    #   "Sam Altman - Co-Founder and CEO @ OpenAI - Crunchbase Person Profile"
    #   "Name | Crunchbase"
    #   "Name - Crunchbase Person Profile"
    name = title

    # Strip Crunchbase suffix first
    name = re.sub(r"\s*[\|·\-]\s*Crunchbase.*$", "", name, flags=re.IGNORECASE).strip()
    # Strip role/company suffix: "Name - Role @ Company" or "Name - Role"
    name = re.sub(r"\s*[\-]\s*(?:Co-?)?(?:Founder|CEO|CTO|COO|President|Managing|Partner|General).*$",
                  "", name, flags=re.IGNORECASE).strip()

    # Try to find company/role in title and body
    company = ""
    role = "Founder"

    # Check title for "@ Company" pattern
    at_match = re.search(r"[@]\s*([A-Z][a-zA-Z0-9\s&.]+?)(?:\s*[-|]|$)", title)
    if at_match:
        company = at_match.group(1).strip()
        role_type = re.search(r"(Co-?Founder|Founder|CEO|CTO|COO)", title, re.IGNORECASE)
        if role_type:
            role = role_type.group(1).replace("-", "-")

    # Fallback: Body snippets often mention "Founder of X" or "CEO at X"
    if not company:
        role_match = re.search(
            r"(?:founder|co-founder|CEO|CTO)\s+(?:of|at)\s+([A-Z][a-zA-Z0-9\s&.]+?)(?:\.|,|\s{2}|$)",
            body, re.IGNORECASE
        )
        if role_match:
            company = role_match.group(1).strip()
            role_type = re.search(r"(founder|co-founder|CEO|CTO)", body, re.IGNORECASE)
            if role_type:
                role = role_type.group(1).title()

    return {"name": name, "company": company, "role": role, "product_desc": _extract_product(body)}


def _parse_twitter(href: str, title: str, body: str) -> Optional[Dict[str, str]]:
    """Parse a Twitter/X profile result."""
    # URL: twitter.com/username or x.com/username
    handle_match = re.search(r"(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)", href)
    if not handle_match:
        return None
    handle = handle_match.group(1)

    # Skip common non-profile pages
    if handle.lower() in ("home", "search", "explore", "login", "i", "hashtag", "settings"):
        return None

    # Title: "Name (@handle) / X" or "Name (@handle) | Twitter"
    # Remove (@handle) and everything after it
    name = re.sub(r"\s*\(@?\w+\).*$", "", title).strip()
    # Remove " / X", " | Twitter", " - X" suffixes
    name = re.sub(r"\s*[\|·/\-]\s*(?:Twitter|X)\s*$", "", name, flags=re.IGNORECASE).strip()

    # Try to extract role/company from bio in body
    company = ""
    role = "Founder"

    role_match = re.search(
        r"(?:founder|co-founder|CEO|CTO|building)\s+(?:of\s+|at\s+|@\s*)?([A-Z][a-zA-Z0-9\s&.]+?)(?:\.|,|\s{2}|\||$)",
        body, re.IGNORECASE
    )
    if role_match:
        company = role_match.group(1).strip()

    if not name or len(name) < 2:
        return None

    # If no company from bio, try harder with body text
    if not company and body:
        company = _extract_company_from_text(body)

    return {"name": name, "company": company, "role": role, "product_desc": _extract_product(body)}


def _parse_generic(href: str, title: str, body: str) -> Optional[Dict[str, str]]:
    """Generic parser for community/fellowship/other sources."""
    # Clean title — remove common suffixes
    name = title
    for suffix in [
        r"\s*[\|·\-]\s*(?:On Deck|Entrepreneur First|Buildspace|Pioneer|Techstars|"
        r"Product Hunt|AngelList|Wellfound|Y Combinator).*$",
        r"\s*[\|·\-]\s*Medium.*$",
        r"\s*[\|·\-]\s*LinkedIn.*$",
    ]:
        name = re.sub(suffix, "", name, flags=re.IGNORECASE).strip()

    company = ""
    role = "Founder"

    # Try to extract "Name - Role at Company" or "Name, Role at Company"
    split_match = re.match(r"^([^,\-|]+?)(?:\s*[-,|]\s*)(.+)$", name)
    if split_match:
        name = split_match.group(1).strip()
        rest = split_match.group(2).strip()
        at_match = re.match(r"(.+?)\s+(?:at|@)\s+(.+)", rest, re.IGNORECASE)
        if at_match:
            role = at_match.group(1).strip()
            company = at_match.group(2).strip()
        else:
            # Could be a company name or role
            if any(kw in rest.lower() for kw in ["founder", "ceo", "cto", "building"]):
                role = rest
            else:
                company = rest

    # If name is too long or looks like a sentence, try to extract from body
    if len(name) > 40 or " is " in name.lower() or not _looks_like_person_name(name):
        founder_match = re.search(
            r"(?:founder|co-founder|CEO|CTO)\s+(?:of\s+\w+\s+)?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})",
            body, re.IGNORECASE
        )
        if founder_match:
            name = founder_match.group(1).strip()
        else:
            return None

    # Clean up
    name = re.sub(r"\s+", " ", name).strip()
    if not name or len(name) < 2 or len(name) > 40:
        return None

    # If no company found, try extracting from body
    if not company and body:
        company = _extract_company_from_text(body)

    return {"name": name, "company": company, "role": role, "product_desc": _extract_product(body)}
