"""Product evaluator: assess a founder's product/service from scraped data.

Runs locally with zero API calls. Evaluates product on five dimensions
using keyword and signal analysis from search snippets, company info,
and enrichment data.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


def evaluate_product(
    product_desc: Optional[str] = None,
    company: Optional[str] = None,
    industry: Optional[str] = None,
    role: Optional[str] = None,
    stage: Optional[str] = None,
    enrichment_summary: Optional[str] = None,
) -> Dict:
    """Evaluate a founder's product and return scores + assessment.

    Returns:
        {
            "product_score": int (0-100),
            "market_potential": str ("High" / "Medium" / "Low"),
            "innovation_signal": str ("Strong" / "Moderate" / "Weak"),
            "scalability": str ("High" / "Medium" / "Low"),
            "product_stage": str ("Idea" / "MVP" / "Growth" / "Scale"),
            "verdict": str (1-2 sentence assessment),
            "strengths": List[str],
            "risks": List[str],
        }
    """
    # Combine all text for analysis
    text = " ".join(filter(None, [
        product_desc, company, industry, role, enrichment_summary,
    ])).lower()

    if not text.strip():
        return _empty_eval()

    # --- Score each dimension ---
    market_score = _score_market(text, industry)
    innovation_score = _score_innovation(text)
    scalability_score = _score_scalability(text)
    stage_score, stage_label = _score_stage(text, stage)
    traction_score = _score_traction(text)

    # Weighted product score
    product_score = int(
        market_score * 0.30
        + innovation_score * 0.25
        + scalability_score * 0.20
        + traction_score * 0.15
        + stage_score * 0.10
    )
    product_score = max(10, min(95, product_score))

    # Derive labels
    market_label = "High" if market_score >= 65 else ("Medium" if market_score >= 40 else "Low")
    innovation_label = "Strong" if innovation_score >= 65 else ("Moderate" if innovation_score >= 40 else "Weak")
    scalability_label = "High" if scalability_score >= 65 else ("Medium" if scalability_score >= 40 else "Low")

    # Build strengths and risks
    strengths = _extract_strengths(text, market_score, innovation_score, scalability_score, traction_score)
    risks = _extract_risks(text, market_score, innovation_score, scalability_score, traction_score, stage_label)

    # Build verdict
    verdict = _build_verdict(product_score, market_label, innovation_label, stage_label, product_desc, company)

    return {
        "product_score": product_score,
        "market_potential": market_label,
        "innovation_signal": innovation_label,
        "scalability": scalability_label,
        "product_stage": stage_label,
        "verdict": verdict,
        "strengths": strengths[:3],
        "risks": risks[:3],
    }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

# Hot markets with large TAMs
_HOT_MARKETS = {
    "ai": 30, "artificial intelligence": 30, "machine learning": 25, "llm": 25,
    "genai": 25, "generative ai": 25,
    "fintech": 20, "payments": 18, "banking": 18, "insurance": 15,
    "healthtech": 20, "health tech": 20, "biotech": 18, "medtech": 18,
    "saas": 15, "enterprise": 15, "b2b": 12, "cloud": 12,
    "cybersecurity": 20, "security": 15, "infosec": 15,
    "climate": 18, "cleantech": 18, "sustainability": 15, "energy": 15,
    "edtech": 12, "education": 10,
    "marketplace": 15, "ecommerce": 12, "e-commerce": 12,
    "developer tools": 18, "devtools": 18, "api": 15, "infrastructure": 15,
    "robotics": 18, "autonomous": 18, "drone": 15,
    "blockchain": 10, "crypto": 8, "web3": 8, "defi": 10,
    "space": 15, "defense": 15, "govtech": 12,
}

_INNOVATION_SIGNALS = {
    "novel": 15, "patent": 15, "breakthrough": 15, "first": 12,
    "proprietary": 12, "disrupting": 12, "reinventing": 12, "pioneering": 12,
    "ai-powered": 10, "ai-native": 10, "automated": 8, "autonomous": 10,
    "open source": 10, "open-source": 10, "research": 8,
    "platform": 8, "ecosystem": 8,
}

_SCALABILITY_SIGNALS = {
    "platform": 15, "saas": 15, "api": 15, "cloud": 12,
    "marketplace": 12, "network effect": 15, "viral": 12,
    "self-serve": 12, "freemium": 10, "recurring": 12,
    "subscription": 12, "automated": 10, "scalable": 10,
    "global": 10, "enterprise": 10, "b2b": 8,
}

_TRACTION_SIGNALS = {
    "revenue": 15, "customers": 15, "users": 12, "growing": 10,
    "raised": 10, "funded": 10, "yc": 12, "y combinator": 12,
    "launched": 8, "live": 8, "shipped": 8, "beta": 5,
    "profitable": 15, "arr": 15, "mrr": 12,
    "hiring": 8, "team of": 6, "employees": 6,
    "award": 8, "featured": 6, "press": 5,
    "partnership": 8, "pilot": 6, "contract": 8,
}


def _count_signals(text: str, signals: Dict[str, int]) -> int:
    score = 0
    for keyword, weight in signals.items():
        if keyword in text:
            score += weight
    return score


def _score_market(text: str, industry: Optional[str]) -> int:
    score = _count_signals(text, _HOT_MARKETS)
    if industry:
        score += _count_signals(industry.lower(), _HOT_MARKETS)
    return min(95, max(15, score + 20))


def _score_innovation(text: str) -> int:
    score = _count_signals(text, _INNOVATION_SIGNALS)
    return min(95, max(15, score + 25))


def _score_scalability(text: str) -> int:
    score = _count_signals(text, _SCALABILITY_SIGNALS)
    return min(95, max(15, score + 20))


def _score_traction(text: str) -> int:
    score = _count_signals(text, _TRACTION_SIGNALS)
    return min(95, max(10, score + 15))


def _score_stage(text: str, stage: Optional[str]) -> tuple:
    stage_str = (stage or "").lower()
    if any(kw in text or kw in stage_str for kw in ["series b", "series c", "growth", "scale", "ipo"]):
        return 80, "Scale"
    if any(kw in text or kw in stage_str for kw in ["series a", "growing", "revenue", "customers"]):
        return 65, "Growth"
    if any(kw in text or kw in stage_str for kw in ["seed", "launched", "mvp", "beta", "live", "shipped"]):
        return 45, "MVP"
    if any(kw in text or kw in stage_str for kw in ["pre-seed", "idea", "stealth", "building"]):
        return 25, "Idea"
    return 35, "MVP"


# ---------------------------------------------------------------------------
# Strengths / Risks / Verdict
# ---------------------------------------------------------------------------

def _extract_strengths(text: str, market: int, innov: int, scale: int, traction: int) -> List[str]:
    strengths = []
    if market >= 65:
        # Find which market
        for kw in ["ai", "fintech", "healthtech", "cybersecurity", "saas", "climate", "developer tools"]:
            if kw in text:
                strengths.append(f"Large addressable market ({kw.upper()})")
                break
        else:
            strengths.append("Strong market opportunity")
    if innov >= 65:
        strengths.append("Shows strong innovation signals")
    if scale >= 65:
        strengths.append("Highly scalable business model")
    if traction >= 55:
        strengths.append("Evidence of early traction")
    if "yc" in text or "y combinator" in text:
        strengths.append("Y Combinator backed")
    if "open source" in text or "open-source" in text:
        strengths.append("Open-source community advantage")
    if not strengths:
        strengths.append("Early-stage opportunity")
    return strengths


def _extract_risks(text: str, market: int, innov: int, scale: int, traction: int, stage: str) -> List[str]:
    risks = []
    if traction < 35:
        risks.append("Limited traction signals")
    if innov < 40:
        risks.append("Low differentiation in crowded market")
    if scale < 40:
        risks.append("Scalability concerns")
    if market < 40:
        risks.append("Niche or unproven market")
    if stage in ("Idea", "MVP"):
        risks.append(f"Early stage ({stage}) — execution risk")
    if "crypto" in text or "web3" in text or "blockchain" in text:
        risks.append("Regulatory and market volatility risk")
    if not risks:
        risks.append("Insufficient data for full risk assessment")
    return risks


def _build_verdict(score: int, market: str, innov: str, stage: str,
                   product_desc: Optional[str], company: Optional[str]) -> str:
    product_name = company or "This product"

    if score >= 75:
        return f"{product_name} operates in a {market.lower()}-potential market with {innov.lower()} innovation signals. Strong fundamentals at {stage} stage."
    elif score >= 55:
        return f"{product_name} shows promising signals in a {market.lower()}-potential market. Currently at {stage} stage with room to grow."
    elif score >= 35:
        return f"{product_name} is at {stage} stage with {market.lower()} market potential. More traction data needed to fully assess."
    else:
        return f"Limited data available on {product_name}. Early indicators suggest {market.lower()} market potential at {stage} stage."


def _empty_eval() -> Dict:
    return {
        "product_score": 0,
        "market_potential": "Unknown",
        "innovation_signal": "Unknown",
        "scalability": "Unknown",
        "product_stage": "Unknown",
        "verdict": "Not enough product information available to evaluate.",
        "strengths": [],
        "risks": ["Insufficient product data"],
    }
