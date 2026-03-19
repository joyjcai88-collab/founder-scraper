"""Vercel serverless entry point — re-exports the FastAPI app."""

import sys
from pathlib import Path

# Ensure the project root is on the Python path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app  # noqa: E402, F401
