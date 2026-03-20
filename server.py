"""FastAPI web interface for the founder scraper."""

import asyncio
from functools import partial
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from analyzer.enricher import enrich_founder
from analyzer.scorer import score_founder
from models.founder import FounderCard, PDLData
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


class ScoreResponse(BaseModel):
    card: FounderCard
    enrichment: Optional[PDLData] = None


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

    return ScoreResponse(card=card, enrichment=profile.pdl)


def _sync_score(profile):
    """Wrapper to call the async score_founder synchronously in an executor."""
    import asyncio
    return asyncio.run(score_founder(profile))
