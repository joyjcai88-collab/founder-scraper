from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class GitHubData(BaseModel):
    username: Optional[str] = None
    profile_url: Optional[str] = None
    bio: Optional[str] = None
    public_repos: int = 0
    followers: int = 0
    top_languages: List[str] = Field(default_factory=list)
    total_stars: int = 0
    recent_activity: Optional[str] = None
    notable_repos: List[Dict] = Field(default_factory=list)


class CrunchbaseData(BaseModel):
    profile_url: Optional[str] = None
    title: Optional[str] = None
    company_name: Optional[str] = None
    company_description: Optional[str] = None
    funding_rounds: List[Dict] = Field(default_factory=list)
    total_funding: Optional[str] = None
    prior_companies: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    investors: List[str] = Field(default_factory=list)


class TwitterData(BaseModel):
    username: Optional[str] = None
    profile_url: Optional[str] = None
    bio: Optional[str] = None
    followers: int = 0
    following: int = 0
    post_count: int = 0
    recent_topics: List[str] = Field(default_factory=list)


class LinkedInData(BaseModel):
    """LinkedIn profile data via RapidAPI."""
    profile_url: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[str] = None
    followers: int = 0
    connections: int = 0
    experience: List[Dict] = Field(default_factory=list)
    education: List[Dict] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    certifications: List[Dict] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


class PDLData(BaseModel):
    """People Data Labs enrichment data — work history, education, social profiles."""
    linkedin_url: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[str] = None
    industry: Optional[str] = None
    experience: List[Dict] = Field(default_factory=list)
    education: List[Dict] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    social_profiles: List[str] = Field(default_factory=list)
    likelihood: int = 0


class WebSearchData(BaseModel):
    snippets: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)


class FounderProfile(BaseModel):
    name: str
    company: Optional[str] = None
    github: Optional[GitHubData] = None
    crunchbase: Optional[CrunchbaseData] = None
    twitter: Optional[TwitterData] = None
    linkedin: Optional[LinkedInData] = None
    pdl: Optional[PDLData] = None
    web_search: Optional[WebSearchData] = None

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
            if self.crunchbase.funding_rounds:
                parts.append("Funding Rounds:")
                for fr in self.crunchbase.funding_rounds[:8]:
                    round_type = fr.get("type", "Unknown")
                    amount = fr.get("amount", "")
                    date = fr.get("date", "")
                    lead = fr.get("lead_investors", [])
                    line = f"  - {round_type}"
                    if amount:
                        line += f": {amount}"
                    if date:
                        line += f" ({date})"
                    if lead:
                        line += f" — led by {', '.join(lead)}"
                    parts.append(line)
            if self.crunchbase.investors:
                parts.append(f"Investors: {', '.join(self.crunchbase.investors)}")
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

        if self.linkedin:
            parts.append("\n--- LinkedIn ---")
            if self.linkedin.headline:
                parts.append(f"Headline: {self.linkedin.headline}")
            if self.linkedin.summary:
                parts.append(f"Summary: {self.linkedin.summary[:500]}")
            if self.linkedin.location:
                parts.append(f"Location: {self.linkedin.location}")
            parts.append(f"Followers: {self.linkedin.followers}")
            parts.append(f"Connections: {self.linkedin.connections}")
            if self.linkedin.experience:
                parts.append("Work Experience:")
                for exp in self.linkedin.experience[:6]:
                    title = exp.get("title", "?")
                    company = exp.get("company", "?")
                    start = exp.get("start_date", "")
                    end = exp.get("end_date", "Present")
                    parts.append(f"  - {title} at {company} ({start} - {end})")
            if self.linkedin.education:
                parts.append("Education:")
                for edu in self.linkedin.education[:4]:
                    school = edu.get("school", "?")
                    degree = edu.get("degree", "")
                    field = edu.get("field", "")
                    desc = f"{degree} in {field}" if degree and field else degree or field
                    parts.append(f"  - {desc} @ {school}" if desc else f"  - {school}")
            if self.linkedin.skills:
                parts.append(f"Skills: {', '.join(self.linkedin.skills[:20])}")

        if self.pdl:
            parts.append("\n--- People Data Labs ---")
            if self.pdl.headline:
                parts.append(f"Headline: {self.pdl.headline}")
            if self.pdl.summary:
                parts.append(f"Summary: {self.pdl.summary}")
            if self.pdl.location:
                parts.append(f"Location: {self.pdl.location}")
            if self.pdl.industry:
                parts.append(f"Industry: {self.pdl.industry}")
            if self.pdl.experience:
                parts.append("Work Experience:")
                for exp in self.pdl.experience[:6]:
                    title = exp.get("title", "?")
                    company = exp.get("company", "?")
                    start = exp.get("start_date", "")
                    end = exp.get("end_date", "present")
                    parts.append(f"  - {title} at {company} ({start} - {end})")
            if self.pdl.education:
                parts.append("Education:")
                for edu in self.pdl.education[:3]:
                    school = edu.get("school", "?")
                    degree = edu.get("degree", "")
                    major = edu.get("major", "")
                    desc = f"{degree} in {major}" if degree and major else degree or major
                    parts.append(f"  - {desc} @ {school}" if desc else f"  - {school}")
            if self.pdl.skills:
                parts.append(f"Skills: {', '.join(self.pdl.skills[:15])}")
            parts.append(f"Match confidence: {self.pdl.likelihood}/10")

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
    company: Optional[str] = None
    overall_score: float = 0.0
    breakdown: Optional[ScoreBreakdown] = None
    thesis_fit_summary: str = ""
    key_risks: List[str] = Field(default_factory=list)
    source_links: List[str] = Field(default_factory=list)
