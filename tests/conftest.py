"""Pytest configuration for ScholarFlow tests.

Ensures project root is on sys.path so `backend.*` imports work,
and provides a fixture to force API_MOCK + LLM_MOCK mode for hermetic tests.
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
    """Patch API_MOCK and LLM_MOCK flags on all relevant modules so tests
    don't hit the network or external LLM providers.

    `backend.config` uses `load_dotenv(override=True)`, so the .env file will
    override any env-var we set before the import. Instead, we flip the
    module-level constants after import.

    LLM_MOCK is re-exported by `backend.config` and re-imported by
    `backend.utils.llm_client` (the actual decision point in `call_llm`).
    We patch both so that whichever module is looked up at call time, the
    mock short-circuit fires — preventing accidental real-LLM traffic when
    a developer happens to have API keys configured locally.
    """
    import backend.api.semantic_scholar as ss_mod
    import backend.api.openalex as oa_mod
    import backend.config as cfg_mod
    import backend.utils.llm_client as llm_mod

    monkeypatch.setattr(ss_mod, "API_MOCK", True)
    monkeypatch.setattr(oa_mod, "API_MOCK", True)
    monkeypatch.setattr(cfg_mod, "LLM_MOCK", True)
    monkeypatch.setattr(llm_mod, "LLM_MOCK", True)
    return monkeypatch
