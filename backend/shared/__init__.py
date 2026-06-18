"""Shared data layer for ScholarFlow backends (v1 LangGraph + v3 mock).

Pure data types — must NOT import from backend.agents / backend.api /
backend.auth or any other backend module. May import from typing /
dataclasses / pydantic only.
"""
from backend.shared.paper_model import Paper, PaperSource
from backend.shared.pipeline_state import PipelineState, NodeId

__all__ = ["Paper", "PaperSource", "PipelineState", "NodeId"]