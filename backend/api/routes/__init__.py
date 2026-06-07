"""ScholarFlow backend HTTP route subpackage.

Each submodule owns a `router = APIRouter(...)` and is mounted by
`backend.main` via `app.include_router(...)`. This keeps `main.py`
slim and groups related endpoints (health probes, search/stream,
cancel, etc.) by responsibility.
"""
