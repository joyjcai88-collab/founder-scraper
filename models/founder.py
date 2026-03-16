from __future__ import annotations

from pydantic import BaseModel, Field


class GitHubData(BaseModel):
    username: str | None = None
    profile_url: str | None = None
    bio: str | None = None
    public_repos: int = 0
    followers: int = 0
    top_languages: list[str] = Field(default_factory=list)
    total_stars: int = 0
    recent_activity: str | None = None
    notable_repos: list[dict] = Field(default_factory=list)


class CrunchbaseData(BaseModel):
    profile_url: str | None = None
    title: str | None = None
    company_name: str | None = None
    company_description: str | None = None
    funding_rounds: list[dict] = Field(default_factory=list)
    total_funding: str | None = None
    prior_companies: list[str] = Field(default_factory=list)
    location: str | None = None


class TwitterData(BaseModel):
    username: str | None = None
    profile_url: str | None = None
    bio: str | None = None
    followers: int = 0
    following: int = 0
    post_count: int = 0
    recent_topics: list[str] = Field(default_factory=list)


class WebSearchData(BaseModel):
    snippets: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class FounderProfile(BaseModel):
    name: str
    company: str | None = None
    github: GitHubData | None = None
    crunchbase: CrunchbaseData | None = None
    twitter: TwitterData | None = None
    web_search: WebSearchData | None = None

    def to_context_string(self) -> str:
        """Serialize profile into a text block for LLM analysis."""
        parts = [f"Founder: {self.name}"]
        if self.company:
            parts.append(f"Company: {self.company}")

        if self.github:
            parts.append("\n--- GitHub ---")
            if self.github.bio:
                parts.append(f"Bio: {self.github.bio}")
            parts.append(f"Public repos: {self.github.public_repos}")
            parts.append(f"Followers: {self.github.followers}")
            parts.append(f"Total stars: {self.github.total_stars}")
            if self.github.top_languages:
                parts.append(f"Top languages: {', '.join(self.github.top_languages)}")
            if self.github.notable_repos:
                for repo in self.github.notable_repos[:5]:
                    parts.append(f"  Repo: {repo.get('name', '?')} ({repo.get('stars', 0)} stars) - {repo.get('description', 'no description')}")

        if self.crunchbase:
            parts.append("\n--- Crunchbase ---")
            if self.crunchbase.title:
                parts.append(f"Title: {self.crunchbase.title}")
            if self.crunchbase.company_name:
                parts.append(f"Company: {self.crunchbase.company_name}")
            if self.crunchbase.company_description:
                parts.append(f"Description: {self.crunchbase.company_description}")
            if self.crunchbase.total_funding:
                parts.append(f"Total funding: {self.crunchbase.total_funding}")
            if self.crunchbase.prior_companies:
                parts.append(f"Prior companies: {', '.join(self.crunchbase.prior_companies)}")
            if self.crunchbase.location:
                parts.append(f"Location: {self.crunchbase.location}")

        if self.twitter:
            parts.append("\n--- Twitter/X ---")
            if self.twitter.bio:
                parts.append(f"Bio: {self.twitter.bio}")
            parts.append(f"Followers: {self.twitter.followers}")
            if self.twitter.recent_topics:
                parts.append(f"Recent topics: {', '.join(self.twitter.recent_topics)}")

        if self.web_search and self.web_search.snippets:
            parts.append("\n--- Web Search Results ---")
            for snippet in self.web_search.snippets[:10]:
                parts.append(f"  - {snippet}")

        return "\n".join(parts)


class ScoreBreakdown(BaseModel):
    founder_quality: int = Field(ge=0, le=100, description="Founder quality score")
    founder_quality_rationale: str = ""
    market: int = Field(ge=0, le=100, description="Market score")
    market_rationale: str = ""
    traction: int = Field(ge=0, le=100, description="Traction score")
    traction_rationale: str = ""
    network: int = Field(ge=0, le=100, description="Network score")
    network_rationale: str = ""
    intangibles: int = Field(ge=0, le=100, description="Intangibles score")
    intangibles_rationale: str = ""


class FounderCard(BaseModel):
    name: str
    company: str | None = None
    overall_score: float = 0.0
    breakdown: ScoreBreakdown | None = None
    thesis_fit_summary: str = ""
    key_risks: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
