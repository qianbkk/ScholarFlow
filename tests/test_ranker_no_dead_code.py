"""Dead-code guard: ensure the legacy single-paper LLM scorers are gone.

`_score_relevance` and `_score_consistency` have been replaced by the batch
implementation `_score_papers_combined_batch`. The two per-paper coroutines
were kept around as dead code for a while; this test pins the removal.
"""
from backend.agents import ranker_agent


def test_no_dead_score_relevance_function():
    """_score_relevance must not be exported from ranker_agent."""
    assert not hasattr(ranker_agent, "_score_relevance"), (
        "Dead function _score_relevance was reintroduced; "
        "use _score_papers_combined_batch instead."
    )


def test_no_dead_score_consistency_function():
    """_score_consistency must not be exported from ranker_agent."""
    assert not hasattr(ranker_agent, "_score_consistency"), (
        "Dead function _score_consistency was reintroduced; "
        "use _score_papers_combined_batch instead."
    )


def test_combined_batch_scorer_still_present():
    """The replacement must still exist after the dead-code removal."""
    assert hasattr(ranker_agent, "_score_papers_combined_batch")
    assert callable(ranker_agent._score_papers_combined_batch)
