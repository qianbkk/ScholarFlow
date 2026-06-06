"""Fix 2: Venue bonus table completeness.

The ranker's authority score applies a per-venue bonus.  Several important
conferences were missing from the table, so papers in those venues got the
default 0.0 bonus and ranked lower than warranted.

Required bonus keys (and the per-test cases):
  * SIGMOD/VLDB (databases)            -> 0.25
  * FSE/ICSE  (software engineering)   -> 0.2
  * CHI      (HCI)                     -> 0.2
  * COLM     (language models, 2024+)  -> 0.3
  * TheWebConf (WWW formal name)       -> 0.2
  * SIGGRAPH (graphics)                -> 0.3
  * STOC/FOCS (theory CS)              -> 0.3
  * RECOMB    (computational biology)  -> 0.25
  * MICCAI    (medical imaging)        -> 0.2  (already present, verified)
"""
import pytest

from backend.agents import ranker_agent


REQUIRED_VENUE_BONUSES = {
    "SIGMOD": 0.25,
    "VLDB": 0.25,
    "FSE": 0.2,
    "ICSE": 0.2,
    "CHI": 0.2,
    "COLM": 0.3,
    "TheWebConf": 0.2,
    "SIGGRAPH": 0.3,
    "STOC": 0.3,
    "FOCS": 0.3,
    "RECOMB": 0.25,
    "MICCAI": 0.2,
}


def test_venue_bonus_table_complete():
    """All required venues must be present in the _VENUE_BONUS table."""
    missing = [v for v in REQUIRED_VENUE_BONUSES if v not in ranker_agent._VENUE_BONUS]
    assert not missing, f"missing venue bonus entries: {missing}"

    for venue, expected_bonus in REQUIRED_VENUE_BONUSES.items():
        actual_bonus = ranker_agent._VENUE_BONUS[venue]
        assert actual_bonus == pytest.approx(expected_bonus, abs=1e-9), (
            f"{venue}: expected bonus {expected_bonus}, got {actual_bonus}"
        )


def test_venue_bonus_returns_correct_score():
    """_authority_score(0, 'NeurIPS') should be 2.0 (base) + 0.3 (NeurIPS bonus)."""
    score = ranker_agent._authority_score(0, "NeurIPS")
    assert score == pytest.approx(2.3, abs=1e-9), (
        f"NeurIPS score with 0 citations should be 2.3 (base 2.0 + bonus 0.3), got {score}"
    )
