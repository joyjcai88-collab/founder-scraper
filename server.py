"""FastAPI web interface for the founder scraper."""

import asyncio
import logging
from functools import partial
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from analyzer.discovery import discover_founders, get_available_sources
from analyzer.enricher import enrich_founder
from analyzer.product_eval import evaluate_product
from analyzer.scorer import score_founder
from models.founder import FounderCard, LinkedInData, PDLData
from scraper.linkedin import (
    build_auth_url,
    exchange_code_for_token,
    fetch_linkedin_profile,
    is_linkedin_configured,
)
from scraper.safety import sanitize_input
from database import (
    save_founder,
    list_saved_founders,
    get_saved_founder,
    update_founder_notes,
    delete_saved_founder,
    is_founder_saved,
    export_csv,
    export_json,
)

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
    industry: Optional[str] = None
    stage: Optional[str] = None
    product: Optional[str] = None
    date_founded: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=25)
    sources: Optional[List[str]] = None


class FounderResult(BaseModel):
    name: str
    company: Optional[str] = None
    role: Optional[str] = None
    industry: Optional[str] = None
    stage: Optional[str] = None
    date_founded: Optional[str] = None
    product: Optional[str] = None
    product_desc: Optional[str] = None
    product_eval: Optional[Dict] = None
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
    parts = []
    if req.industry:
        parts.append(sanitize_input(req.industry))
    if req.stage:
        parts.append(sanitize_input(req.stage))
    if req.product:
        parts.append(sanitize_input(req.product))
    if req.date_founded:
        parts.append(f"founded {sanitize_input(req.date_founded)}")
    query_summary = " / ".join(parts) if parts else "All founders"

    # Discover founders via multi-source search
    raw_founders = await discover_founders(
        industry=req.industry,
        stage=req.stage,
        product=req.product,
        date_founded=req.date_founded,
        limit=req.limit,
        sources=req.sources,
    )

    print(f"[server] Discovery returned {len(raw_founders)} raw founders for query: {query_summary}", flush=True)
    if not raw_founders:
        return DiscoverResponse(query=query_summary, founders=[])

    # Search criteria to attach to each result
    s_industry = sanitize_input(req.industry) if req.industry else None
    s_stage = sanitize_input(req.stage) if req.stage else None
    s_product = sanitize_input(req.product) if req.product else None
    s_date = sanitize_input(req.date_founded) if req.date_founded else None

    # Enrich and score each founder concurrently
    async def _process_one(entry: Dict) -> FounderResult:
        name = sanitize_input(entry.get("name", ""))
        company = sanitize_input(entry.get("company", "")) or None
        role = entry.get("role", "")
        product_desc = entry.get("product_desc", "") or None
        source = entry.get("source", "")
        url = entry.get("url", "")
        if not name:
            return None  # Skip — no founder name
        if not company and not product_desc:
            return None  # Skip — no company or product

        # Evaluate product (runs locally, no API needed)
        p_eval = evaluate_product(
            product_desc=product_desc,
            company=company,
            industry=s_industry,
            role=role,
            stage=s_stage,
        )

        try:
            profile = await enrich_founder(name, company)

            # Re-evaluate with enrichment data for better accuracy
            enrichment_text = ""
            if profile.pdl and profile.pdl.summary:
                enrichment_text = profile.pdl.summary
            elif profile.linkedin and profile.linkedin.headline:
                enrichment_text = profile.linkedin.headline
            if enrichment_text:
                p_eval = evaluate_product(
                    product_desc=product_desc,
                    company=company,
                    industry=s_industry,
                    role=role,
                    stage=s_stage,
                    enrichment_summary=enrichment_text,
                )

            loop = asyncio.get_event_loop()
            card = await loop.run_in_executor(
                None, partial(_sync_score, profile)
            )
            return FounderResult(
                name=name,
                company=company,
                role=role,
                industry=s_industry,
                stage=s_stage,
                date_founded=s_date,
                product=s_product,
                product_desc=product_desc,
                product_eval=p_eval,
                source=source,
                url=url,
                card=card,
                enrichment=profile.pdl,
                linkedin=profile.linkedin,
            )
        except Exception as e:
            return FounderResult(
                name=name, company=company, role=role,
                industry=s_industry, stage=s_stage,
                date_founded=s_date, product=s_product,
                product_desc=product_desc,
                product_eval=p_eval,
                source=source, url=url, error=str(e),
            )

    raw_results = await asyncio.gather(*[_process_one(f) for f in raw_founders])

    # Filter out None results (missing name or company)
    results = [r for r in raw_results if r is not None]

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


@app.get("/api/debug/search")
async def api_debug_search(q: str = "AI startup founder"):
    """Lightweight diagnostic: test DuckDuckGo search from this server."""
    from scraper.ddg import ddg_search
    results = ddg_search(q, max_results=3)
    return {
        "query": q,
        "count": len(results),
        "results": [
            {"title": r.get("title", "")[:100], "href": r.get("href", ""), "body": r.get("body", "")[:200]}
            for r in results
        ],
    }


# --- Saved Founders endpoints ---

class SaveFounderRequest(BaseModel):
    name: str
    company: Optional[str] = None
    role: Optional[str] = None
    industry: Optional[str] = None
    stage: Optional[str] = None
    date_founded: Optional[str] = None
    product: Optional[str] = None
    product_desc: Optional[str] = None
    product_eval: Optional[Dict] = None
    source: Optional[str] = None
    url: Optional[str] = None
    overall_score: Optional[float] = None
    card: Optional[Dict] = None
    enrichment: Optional[Dict] = None
    linkedin: Optional[Dict] = None
    notes: Optional[str] = ""
    search_query: Optional[str] = None


class UpdateNotesRequest(BaseModel):
    notes: str


@app.get("/api/saved")
async def api_list_saved():
    """List all saved founder profiles."""
    founders = list_saved_founders()
    return {"founders": founders, "count": len(founders)}


@app.post("/api/saved")
async def api_save_founder(req: SaveFounderRequest):
    """Save a founder profile to the database."""
    # Check if already saved
    existing_id = is_founder_saved(req.name, req.company)
    if existing_id:
        return {"id": existing_id, "already_saved": True}

    row_id = save_founder(req.dict())
    return {"id": row_id, "already_saved": False}


@app.get("/api/saved/{founder_id}")
async def api_get_saved(founder_id: int):
    """Get a single saved founder by ID."""
    founder = get_saved_founder(founder_id)
    if not founder:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return founder


@app.put("/api/saved/{founder_id}/notes")
async def api_update_notes(founder_id: int, req: UpdateNotesRequest):
    """Update notes for a saved founder."""
    success = update_founder_notes(founder_id, req.notes)
    if not success:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"updated": True}


@app.delete("/api/saved/{founder_id}")
async def api_delete_saved(founder_id: int):
    """Remove a founder from saved profiles."""
    success = delete_saved_founder(founder_id)
    if not success:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"deleted": True}


@app.get("/api/saved/check/{name}")
async def api_check_saved(name: str, company: Optional[str] = None):
    """Check if a founder is already saved."""
    founder_id = is_founder_saved(name, company)
    return {"saved": founder_id is not None, "id": founder_id}


@app.get("/api/export/csv")
async def api_export_csv():
    """Export all saved founders as CSV."""
    csv_data = export_csv()
    if not csv_data:
        return JSONResponse({"error": "No saved founders to export"}, status_code=404)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=founders.csv"},
    )


@app.get("/api/export/json")
async def api_export_json():
    """Export all saved founders as JSON."""
    data = export_json()
    if not data:
        return JSONResponse({"error": "No saved founders to export"}, status_code=404)
    return JSONResponse(
        content={"founders": data, "exported_at": __import__("datetime").datetime.utcnow().isoformat()},
        headers={"Content-Disposition": "attachment; filename=founders.json"},
    )


def _sync_score(profile):
    """Wrapper to call the async score_founder synchronously in an executor."""
    import asyncio
    return asyncio.run(score_founder(profile))
