"""FastAPI web interface for the founder scraper."""

import asyncio
from functools import partial
from pathlib import Path
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from analyzer.discovery import discover_founders, get_available_sources
from analyzer.enricher import enrich_founder
from analyzer.scorer import score_founder
from models.founder import FounderCard, LinkedInData, PDLData
from scraper.linkedin import (
    build_auth_url,
    exchange_code_for_token,
    fetch_linkedin_profile,
    is_linkedin_configured,
)
from scraper.safety import sanitize_input

load_dotenv()

app = FastAPI(title="Founder Scraper")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# In-memory store for LinkedIn tokens (per-session; use a DB in production)
_linkedin_tokens: Dict[str, str] = {}
_linkedin_profiles: Dict[str, Dict[str, Any]] = {}


class ScoreRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: Optional[str] = None


class DiscoverRequest(BaseModel):
    industry: str = Field(min_length=1, max_length=200)
    stage: Optional[str] = None
    product: Optional[str] = None
    date_founded: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=25)
    sources: Optional[List[str]] = None


class FounderResult(BaseModel):
    name: str
    company: Optional[str] = None
    role: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    card: Optional[FounderCard] = None
    enrichment: Optional[PDLData] = None
    linkedin: Optional[LinkedInData] = None
    error: Optional[str] = None


class DiscoverResponse(BaseModel):
    query: str
    founders: List[FounderResult] = Field(default_factory=list)


class ScoreResponse(BaseModel):
    card: FounderCard
    enrichment: Optional[PDLData] = None
    linkedin: Optional[LinkedInData] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- LinkedIn OAuth endpoints ---

@app.get("/api/linkedin/status")
async def linkedin_status():
    """Check if LinkedIn OAuth is configured and if user is connected."""
    configured = is_linkedin_configured()
    connected = bool(_linkedin_profiles)
    profile = list(_linkedin_profiles.values())[0] if connected else None
    return {
        "configured": configured,
        "connected": connected,
        "profile": profile,
    }


@app.get("/api/linkedin/connect")
async def linkedin_connect():
    """Redirect user to LinkedIn OAuth authorization page."""
    if not is_linkedin_configured():
        return JSONResponse(
            {"error": "LinkedIn OAuth not configured. Set LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, and LINKEDIN_REDIRECT_URI."},
            status_code=400,
        )
    auth_url = build_auth_url()
    return RedirectResponse(url=auth_url)


@app.get("/api/linkedin/callback")
async def linkedin_callback(code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    """Handle LinkedIn OAuth callback — exchange code for token and fetch profile."""
    if error or not code:
        return HTMLResponse(
            f"<html><body><h2>LinkedIn auth failed</h2><p>{error or 'No code received'}</p>"
            f"<p><a href='/'>Back to app</a></p></body></html>",
            status_code=400,
        )

    # Exchange code for token
    token = await exchange_code_for_token(code)
    if not token:
        return HTMLResponse(
            "<html><body><h2>Failed to get LinkedIn token</h2>"
            "<p><a href='/'>Back to app</a></p></body></html>",
            status_code=400,
        )

    # Fetch the user's profile
    profile = await fetch_linkedin_profile(token)
    if not profile:
        return HTMLResponse(
            "<html><body><h2>Failed to fetch LinkedIn profile</h2>"
            "<p><a href='/'>Back to app</a></p></body></html>",
            status_code=400,
        )

    # Store token and profile
    _linkedin_tokens["current"] = token
    _linkedin_profiles["current"] = profile

    # Redirect back to the app with success
    return HTMLResponse(
        "<html><body><script>"
        "window.opener && window.opener.postMessage({type:'linkedin_connected'},'*');"
        "window.close();"
        "</script>"
        "<h2>LinkedIn connected!</h2>"
        "<p>You can close this window and return to the app.</p>"
        "<p><a href='/'>Back to app</a></p></body></html>"
    )


@app.get("/api/linkedin/disconnect")
async def linkedin_disconnect():
    """Disconnect LinkedIn (clear stored token/profile)."""
    _linkedin_tokens.clear()
    _linkedin_profiles.clear()
    return {"disconnected": True}


# --- Scoring endpoint ---

@app.post("/api/score")
async def api_score(req: ScoreRequest) -> ScoreResponse:
    name = sanitize_input(req.name)
    company = sanitize_input(req.company) if req.company else None

    profile = await enrich_founder(name, company)

    # score_founder uses the sync Anthropic client internally, so run in executor
    loop = asyncio.get_event_loop()
    card = await loop.run_in_executor(None, partial(_sync_score, profile))

    return ScoreResponse(card=card, enrichment=profile.pdl, linkedin=profile.linkedin)


@app.post("/api/discover")
async def api_discover(req: DiscoverRequest) -> DiscoverResponse:
    """Discover founders by company criteria (industry, stage, product, date)."""
    # Build a human-readable query summary
    parts = [sanitize_input(req.industry)]
    if req.stage:
        parts.append(sanitize_input(req.stage))
    if req.product:
        parts.append(sanitize_input(req.product))
    if req.date_founded:
        parts.append(f"founded {sanitize_input(req.date_founded)}")
    query_summary = " / ".join(parts)

    # Discover founders via multi-source search
    raw_founders = await discover_founders(
        industry=req.industry,
        stage=req.stage,
        product=req.product,
        date_founded=req.date_founded,
        limit=req.limit,
        sources=req.sources,
    )

    if not raw_founders:
        return DiscoverResponse(query=query_summary, founders=[])

    # Enrich and score each founder concurrently
    async def _process_one(entry: Dict) -> FounderResult:
        name = sanitize_input(entry.get("name", ""))
        company = sanitize_input(entry.get("company", "")) or None
        role = entry.get("role", "")
        source = entry.get("source", "")
        url = entry.get("url", "")
        if not name:
            return FounderResult(name="Unknown", error="No name returned")
        try:
            profile = await enrich_founder(name, company)
            loop = asyncio.get_event_loop()
            card = await loop.run_in_executor(
                None, partial(_sync_score, profile)
            )
            return FounderResult(
                name=name,
                company=company,
                role=role,
                source=source,
                url=url,
                card=card,
                enrichment=profile.pdl,
                linkedin=profile.linkedin,
            )
        except Exception as e:
            return FounderResult(
                name=name, company=company, role=role,
                source=source, url=url, error=str(e),
            )

    results = await asyncio.gather(*[_process_one(f) for f in raw_founders])

    # Sort by overall score (highest first), errors at the end
    scored = sorted(
        results,
        key=lambda r: r.card.overall_score if r.card else -1,
        reverse=True,
    )

    return DiscoverResponse(query=query_summary, founders=scored)


@app.get("/api/sources")
async def api_sources():
    """Return available discovery sources."""
    return get_available_sources()


def _sync_score(profile):
    """Wrapper to call the async score_founder synchronously in an executor."""
    import asyncio
    return asyncio.run(score_founder(profile))
