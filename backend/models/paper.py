"""Paper 数据类 — 跨 API 统一的论文表示。

Paper dataclass now lives in backend.shared.paper_model so both v1
(real LangGraph) and v3 (mock) backends can import it without a
backend.models dependency. This module re-exports for backward compat.
"""
from backend.shared.paper_model import Paper, PaperSource

__all__ = ["Paper", "PaperSource"]


# Re-exported by backend.models.paper for backward compat