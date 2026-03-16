from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ThesisTemplate:
    name: str
    description: str
    weights: dict[str, float] = field(default_factory=dict)
    parameters: dict[str, str] = field(default_factory=dict)


GENERIC_EARLY_STAGE = ThesisTemplate(
    name="Generic Early-Stage Tech",
    description="Generalist early-stage technology thesis targeting Seed to Series A companies.",
    weights={
        "founder_quality": 0.30,
        "market": 0.25,
        "traction": 0.25,
        "network": 0.10,
        "intangibles": 0.10,
    },
    parameters={
        "stage_focus": "Pre-seed to Series A",
        "sector_focus": "Technology (broad)",
        "geography": "Global",
        "check_size": "$500K - $5M",
    },
)


def get_default_thesis() -> ThesisTemplate:
    return GENERIC_EARLY_STAGE
