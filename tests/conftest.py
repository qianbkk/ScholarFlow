"""Pytest configuration for ScholarFlow tests.

Ensures project root is on sys.path so `backend.*` imports work,
and provides a fixture to force API_MOCK mode for hermetic tests.
"""
import os
import sys

# Ensure project root is importable regardless of where pytest is invoked
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import pytest


@pytest.fixture
def force_mock_api(monkeypatch):
    """Patch API_MOCK flag on all API modules so tests don't hit the network.

    `backend.config` uses `load_dotenv(override=True)`, so the .env file will
    override any env-var we set before the import. Instead, we flip the
    module-level constants after import.
    """
    import backend.api.semantic_scholar as ss_mod
    import backend.api.openalex as oa_mod

    monkeypatch.setattr(ss_mod, "API_MOCK", True)
    monkeypatch.setattr(oa_mod, "API_MOCK", True)
    return monkeypatch
