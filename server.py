"""FastAPI web interface for the founder scraper."""

import asyncio
from functools import partial
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from analyzer.enricher import enrich_founder
from analyzer.scorer import score_founder
from models.founder import FounderCard, PDLData
from scraper.safety import sanitize_input

load_dotenv()

app = FastAPI(title="Founder Scraper")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class ScoreRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: Optional[str] = None


class ScoreResponse(BaseModel):
    card: FounderCard
    enrichment: Optional[PDLData] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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
