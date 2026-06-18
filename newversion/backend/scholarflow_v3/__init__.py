"""ScholarFlow v3 backend.

A fresh, self-contained FastAPI app. The 8-node research pipeline is implemented
in `pipeline.py`. All endpoints live under /api/v3/* (the v3 frontend proxies to
this prefix on port 9000).

This package does NOT import from the v1 backend (`../backend/`) — it is a
parallel implementation that you can run side by side.
"""
__version__ = "3.0.0"
