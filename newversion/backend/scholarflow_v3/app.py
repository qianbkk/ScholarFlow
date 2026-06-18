"""FastAPI app factory + route handlers for the v3 backend.

All endpoints are mounted under /api/v3. The v3 frontend (port 6173) proxies
/api/* to this service (port 9000).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import __version__
from .models import HealthResponse, SearchRequest, SearchResult, StreamEvent
from .pipeline import run_pipeline

STARTED_AT = time.time()

# In-memory search registry. Each entry is an asyncio.Event signalling cancel.
_CANCEL_FLAGS: dict[str, asyncio.Event] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ScholarFlow v3",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS: open in dev. In production, restrict to the v3 frontend origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v3/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            nodes=8,
            uptime_seconds=round(time.time() - STARTED_AT, 1),
        )

    @app.post("/api/v3/search", response_model=SearchResult)
    async def search(req: SearchRequest) -> SearchResult:
        """One-shot search — runs the pipeline to completion and returns the result."""
        search_id = f"sfv3_{uuid.uuid4().hex[:10]}"
        result: SearchResult | None = None
        async for item in run_pipeline(req, search_id):
            if isinstance(item, SearchResult):
                result = item
                break
        if result is None:
            raise HTTPException(status_code=500, detail="pipeline did not return a result")
        return result

    @app.post("/api/v3/search/stream")
    async def search_stream(req: SearchRequest):
        """SSE stream: yields node_start, node_end, papers, ranked, critique, cost, then final result."""
        search_id = f"sfv3_{uuid.uuid4().hex[:10]}"
        cancel_event = asyncio.Event()
        _CANCEL_FLAGS[search_id] = cancel_event

        async def event_source() -> AsyncIterator[bytes]:
            try:
                yield _sse({"event": "search_start", "data": {"search_id": search_id}})
                async for item in run_pipeline(req, search_id):
                    if cancel_event.is_set():
                        yield _sse({"event": "cancelled", "data": {"search_id": search_id}})
                        return
                    if isinstance(item, StreamEvent):
                        yield _sse({"event": item.event, "data": item.data, "ts": item.ts, "search_id": search_id})
                    elif isinstance(item, SearchResult):
                        yield _sse({"event": "result", "data": item.model_dump()})
                        yield _sse({"event": "[DONE]", "data": {}})
            finally:
                _CANCEL_FLAGS.pop(search_id, None)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/v3/search/cancel")
    async def cancel_search(payload: dict) -> dict:
        search_id = payload.get("search_id")
        if not search_id:
            raise HTTPException(status_code=400, detail="search_id required")
        ev = _CANCEL_FLAGS.get(search_id)
        if ev is None:
            return {"cancelled": False, "reason": "unknown search_id"}
        ev.set()
        return {"cancelled": True}

    return app


def _sse(payload: dict) -> bytes:
    """Encode a dict as an SSE frame: `data: <json>\n\n`."""
    return f"data: {json.dumps(payload, default=str)}\n\n".encode("utf-8")
