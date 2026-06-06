"""Verify that the `force_mock_api` fixture flips every relevant mock flag.

Before this fixture covered `LLM_MOCK` it was possible to set `API_MOCK=True`
for the academic-API clients but still call out to a real LLM if the
developer had a key configured locally — see conftest.py.

Note: imports happen *inside* each test because `test_cors_hardening.py`
purges `sys.modules['backend.*']` to test reload semantics, and a top-level
import here would leave a stale module reference after the purge.
"""
def test_force_mock_api_sets_api_mock_flags(force_mock_api):
    """Both academic-API clients must report API_MOCK=True under the fixture."""
    import backend.api.semantic_scholar as ss_mod
    import backend.api.openalex as oa_mod

    assert ss_mod.API_MOCK is True
    assert oa_mod.API_MOCK is True


def test_force_mock_api_sets_llm_mock_flags(force_mock_api):
    """Both `backend.config` and `backend.utils.llm_client` must report
    LLM_MOCK=True under the fixture — `call_llm` reads from the llm_client
    module's binding, so patching only `backend.config` is insufficient.
    """
    import backend.config as cfg_mod
    import backend.utils.llm_client as llm_mod

    assert cfg_mod.LLM_MOCK is True
    assert llm_mod.LLM_MOCK is True


def test_force_mock_api_does_not_leak(force_mock_api):
    """Sanity check: inside the fixture, LLM_MOCK is True on the consumer
    module that `call_llm` actually reads from. Pytest's monkeypatch teardown
    restores the original value after the test, but pinning the behavior
    here stops a future refactor from silently breaking the isolation
    contract.
    """
    import backend.utils.llm_client as llm_mod

    assert llm_mod.LLM_MOCK is True
