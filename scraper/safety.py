"""Security utilities for scraping: input sanitization, URL validation, text cleaning."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

MAX_INPUT_LENGTH = 200
MAX_SCRAPED_TEXT_LENGTH = 5000

# Patterns that look like prompt injection attempts
_INSTRUCTION_PATTERNS = re.compile(
    r"(ignore\s+(previous|above|all)\s+instructions|"
    r"you\s+are\s+now|"
    r"system\s*:\s*|"
    r"<\s*/?system\s*>|"
    r"act\s+as\s+|"
    r"pretend\s+to\s+be)",
    re.IGNORECASE,
)

_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
]


def sanitize_input(text: str) -> str:
    """Sanitize user input: strip control chars, enforce length limit."""
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
    return cleaned[:MAX_INPUT_LENGTH].strip()


def is_safe_url(url: str) -> bool:
    """Check that a URL is safe to request (no SSRF to private networks)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname in ("localhost", "metadata.google.internal"):
        return False

    try:
        ip = ipaddress.ip_address(hostname)
        for network in _BLOCKED_IP_NETWORKS:
            if ip in network:
                return False
    except ValueError:
        pass

    return True


def clean_scraped_text(text: str) -> str:
    """Clean scraped text: remove HTML tags, truncate, strip suspicious patterns."""
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = _INSTRUCTION_PATTERNS.sub("[REDACTED]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_SCRAPED_TEXT_LENGTH]
