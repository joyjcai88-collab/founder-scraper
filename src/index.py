"""Vercel FastAPI entry point — re-exports the app from server.py."""

import sys
from pathlib import Path

# Add project root to path so our package imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app  # noqa: E402, F401
