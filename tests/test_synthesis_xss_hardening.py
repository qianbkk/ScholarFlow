"""Tests for H7: DANGEROUS_PATTERNS hardening in synthesis_agent.py.

The audit found that the previous denylist in ``synthesize_node``
missed several XSS vectors:

  * SVG SMIL events  — ``<svg><animate onbegin=alert(1)>``
  * Whitespace obfuscation — ``onerror =alert(1)``
  * HTML-entity / tab obfuscation in URI — ``java&#x09;script:``
  * Dangerous HTML tags — ``<style>``, ``<form>``, ``<input>``,
    ``<link>``, ``<meta>``
  * data:text/html URI scheme

This test mocks ``call_llm`` so the LLM is bypassed entirely — the
denylist runs against attacker-controlled text. Each payload is fed
through ``synthesize_node`` and the result is asserted to be the
fallback report (no XSS payload in the output).
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents import synthesis_agent
from backend.models.state import SearchState


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

def _make_state() -> SearchState:
    """Minimal state with one ranked paper so synthesize_node doesn't bail."""
    return {
        "original_query": "XSS payload probe",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [
            {
                "title": "Test paper",
                "year": 2024,
                "citation_count": 0,
                "venue": "Test",
                "relevance_score": 7.0,
                "authority_score": 5.0,
                "consistency_score": 8.0,
                "final_score": 6.5,
                "url": "https://example.com",
                "abstract": "An abstract.",
            }
        ],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 1,
        "expanded_paper_ids": [],
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 1.0,
        "model_usage": {},
        "status": "synthesizing",
        "error": None,
    }


_FALLBACK_HEADER = "## 研究概述"
"""Marker substring: the fallback report always starts with this exact
header. If the LLM output is not stripped by the denylist, the actual
attacker payload (e.g. ``<svg><animate onbegin=alert(1)></svg>``) will
appear in the report and the fallback header will NOT be at the start."""


async def _run_with_payload(payload: str) -> str:
    """Run synthesize_node with `call_llm` mocked to return `payload`."""
    state = _make_state()
    fake_usage = {
        "model": "mock", "provider": "mock",
        "input_tokens": 10, "output_tokens": 20, "cost_usd": 0.0,
    }
    with patch.object(
        synthesis_agent, "call_llm",
        new=AsyncMock(return_value=(payload, fake_usage)),
    ):
        result = await synthesis_agent.synthesize_node(state)
    return result["report"]


# ---------------------------------------------------------------------------
# Sanity: clean report passes through
# ---------------------------------------------------------------------------

def test_clean_report_passes_through():
    """A benign LLM report (no dangerous tokens) must NOT be replaced
    by the fallback report."""
    clean = (
        "## 研究概述\n"
        "本综述聚焦于多智能体系统的最新进展。\n\n"
        "## 核心论文推荐（Top 5）\n"
        "1. **Some Paper** [2024] — 相关性 8.0/10\n"
    )
    report = asyncio.run(_run_with_payload(clean))
    # The exact clean text should come through
    assert "多智能体系统的最新进展" in report
    assert "Some Paper" in report
    # No fallback header (that is, the header that the fallback always emits
    # in response to a "针对查询「X」" intro). Use a more specific marker:
    assert "由于 LLM 不可用" not in report


# ---------------------------------------------------------------------------
# H7: XSS payloads must trigger the fallback
# ---------------------------------------------------------------------------

def _assert_fallback(report: str, payload: str) -> None:
    """Helper: report must be the fallback (LLM disabled) report and must
    not contain any portion of the attacker payload."""
    assert "由于 LLM 不可用" in report, (
        f"Expected fallback report marker `由于 LLM 不可用` in output, got:\n"
        f"{report[:300]!r}"
    )
    # Make sure the literal payload (or its salient part) is NOT in the
    # report. We strip the payload to its most distinctive token.
    needle = payload.strip().split()[0] if payload.strip() else payload
    # SVG / script / form / style tags, and the bare event handler names
    for forbidden in [
        "<svg", "<script", "<form", "<input", "<style", "<iframe",
        "onerror", "onbegin", "onload", "javascript:", "data:text/html",
    ]:
        assert forbidden not in report.lower(), (
            f"Forbidden token {forbidden!r} leaked into fallback report:\n"
            f"{report[:300]!r}"
        )


def test_svg_smil_onbegin_blocked():
    """<svg><animate onbegin=alert(1)></svg> must be blocked."""
    payload = (
        "## 研究概述\n"
        "<svg><animate onbegin=alert(1)></svg>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_svg_onload_blocked():
    """<svg onload=alert(1)> must be blocked."""
    payload = (
        "## 研究概述\n"
        "<svg onload=alert(1)></svg>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_onerror_with_whitespace_blocked():
    """`onerror =alert(1)` (whitespace before `=`) must be blocked.

    This is the H7 call-out: the previous denylist only matched
    `onerror=` with no whitespace.
    """
    payload = (
        "## 研究概述\n"
        "<img src=x onerror =alert(1)>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_onerror_with_tab_blocked():
    """`onerror\t=alert(1)` (tab before `=`) must be blocked."""
    payload = (
        "## 研究概述\n"
        "<img src=x onerror\t=alert(1)>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_javascript_protocol_with_html_entity_blocked():
    """`<a href="java&#x09;script:alert(1)">` (tab obfuscation) must be
    blocked. Even though the rendered browser may unescape the entity,
    the literal token `javascript:` is what we look for in the lowercased
    report. We feed the un-escaped form here because the LLM would emit
    the textual form before the browser's HTML parser processes it."""
    payload = (
        "## 研究概述\n"
        '<a href="java&#x09;script:alert(1)">click</a>\n'
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_javascript_protocol_plain_blocked():
    """Plain `javascript:` must be blocked (already in old denylist)."""
    payload = (
        "## 研究概述\n"
        '<a href="javascript:alert(1)">click</a>\n'
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_style_tag_blocked():
    """`<style>body{...}` must be blocked."""
    payload = (
        "## 研究概述\n"
        "<style>body{background:url('javascript:alert(1)')}</style>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_form_input_blocked():
    """`<form><input ...>` must be blocked."""
    payload = (
        "## 研究概述\n"
        "<form action=javascript:alert(1)><input type=submit></form>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_data_uri_text_html_blocked():
    """`data:text/html,<script>alert(1)</script>` must be blocked."""
    payload = (
        "## 研究概述\n"
        "data:text/html,<script>alert(1)</script>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_iframe_blocked():
    """`<iframe>` must be blocked (regression check, already in old list)."""
    payload = (
        "## 研究概述\n"
        "<iframe src=javascript:alert(1)></iframe>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)


def test_uppercase_onerror_blocked():
    """Case-insensitive: `ONERROR=` and `OnError =` must also be blocked."""
    payload = (
        "## 研究概述\n"
        "<img src=x ONERROR =alert(1)>\n"
        "## 核心论文\n1. **X** [2024]\n"
    )
    report = asyncio.run(_run_with_payload(payload))
    _assert_fallback(report, payload)
