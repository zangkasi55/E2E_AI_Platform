"""Pytest configuration — ensure the backend package is importable and mock mode
is forced before any app import."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MOCK_MODE", "true")
# Force the LLM layer to stay mocked in tests even if a live ``.env`` sets
# LIVE_LLM=true (OS env vars take precedence over .env in pydantic-settings).
os.environ.setdefault("LIVE_LLM", "false")

# Add backend/ to sys.path so `import app...` works when running pytest from repo root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
