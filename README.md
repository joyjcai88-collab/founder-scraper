# Founder Scraper

AI-powered founder enrichment and scoring tool for VC deal flow. Takes a founder's name, scrapes public data from multiple sources, and outputs a scored founder card analyzed against a configurable investment thesis.

## How it works

```
Founder name → Scrape public data → Enrich profile → Score with Claude → Founder card
```

**Data sources:**
- GitHub (repos, languages, stars, activity)
- Crunchbase (funding history, company info, prior companies)
- Twitter/X (bio, followers, recent topics)
- DuckDuckGo (supplementary web context)

**Scoring categories** (configurable weights):
| Category | Default Weight |
|---|---|
| Founder Quality | 30% |
| Market | 25% |
| Traction | 25% |
| Network | 10% |
| Intangibles | 10% |

Each category is scored 0-100 with a rationale. The overall score is a weighted average.

## Setup

```bash
git clone https://github.com/joyjcai88-collab/founder-scraper.git
cd founder-scraper
pip install -e .
cp .env.example .env
```

Add your Anthropic API key to `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
# Basic usage
python main.py "Tobi Lutke"

# With company name for better accuracy
python main.py "Tobi Lutke" --company "Shopify"

# Short flag
python main.py "Patrick Collison" -c "Stripe"
```

## Output

The CLI outputs a formatted founder card with:
- Overall score (color-coded green/yellow/red)
- Per-category breakdown with bar charts and rationale
- Thesis fit summary
- Key risks and flags
- Source links

## Project Structure

```
founder-scraper/
├── main.py              # CLI entry point
├── scraper/
│   ├── github.py        # GitHub REST API
│   ├── crunchbase.py    # Crunchbase page scraper
│   ├── twitter.py       # Twitter/X via Nitter
│   ├── web_search.py    # DuckDuckGo search
│   └── safety.py        # Input sanitization, SSRF protection
├── analyzer/
│   ├── enricher.py      # Concurrent scraper orchestration
│   └── scorer.py        # Claude API scoring engine
├── models/
│   └── founder.py       # Pydantic data models
└── config/
    └── thesis.py        # Investment thesis templates
```

## Security

- API keys excluded from version control via `.gitignore`
- Input sanitization on all user-provided strings
- SSRF protection blocks requests to private/internal IPs
- Scraped content is delimited and treated as untrusted data in LLM prompts
- All dependencies are version-pinned

## Requirements

- Python 3.9+
- Anthropic API key
