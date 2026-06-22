"""
P10 实测脚本 v3: 自动重启后端清空 in-memory 缓存
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from typing import Optional

import httpx


async def measure_stream(
    query: str,
    api_key: str,
    base_url: str = "http://127.0.0.1:8000",
    max_iter: int = 2,
    paper_max: int = 10,
) -> dict:
    """通过 SSE 流测总耗时 + 各节点耗时."""
    q = urllib.parse.quote(query)
    url = (
        f"{base_url}/api/v1/search/stream"
        f"?q={q}&max_iter={max_iter}&paper_max={paper_max}&paper_min=5"
        f"&provider=minimax&runtime_mode=llm&budget=2.0"
    )
    t0 = time.time()
    node_starts: dict[str, float] = {}
    node_elapsed: dict[str, float] = {}
    papers_count = 0
    cost = 0.0
    error: Optional[str] = None
    timeout = 600.0
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    return {
                        "query": query,
                        "total_sec": round(time.time() - t0, 2),
                        "error": f"HTTP {resp.status_code}: {body.decode('utf-8', errors='replace')[:300]}",
                    }
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if not payload:
                        continue
                    try:
                        evt = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    et = evt.get("event")
                    node = evt.get("node")
                    now = time.time() - t0
                    if et == "node_started" and node:
                        node_starts[node] = now
                    elif et == "node_complete" and node:
                        s = node_starts.get(node, now)
                        node_elapsed[node] = now - s
                    elif et == "done":
                        result = evt.get("result", {})
                        papers_count = len(result.get("ranked_papers", []))
                        cost = result.get("total_cost_usd", 0.0)
                    elif et in ("error", "timeout", "cancelled", "budget_exceeded"):
                        error = evt.get("message") or et
        except httpx.HTTPStatusError as e:
            error = f"HTTP {e.response.status_code}"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
    total = time.time() - t0
    return {
        "query": query,
        "total_sec": round(total, 2),
        "nodes": {k: round(v, 2) for k, v in node_elapsed.items()},
        "cost_usd": cost,
        "papers": papers_count,
        "error": error,
    }


def fmt_result(r: dict) -> str:
    out = ["=== ScholarFlow P10 实测 ==="]
    out.append(f"query: {r['query']}")
    out.append(f"total: {r['total_sec']}s")
    if r.get("error"):
        out.append(f"ERROR: {r['error']}")
    if r.get("nodes"):
        out.append("nodes:")
        for n, t in r["nodes"].items():
            out.append(f"  {n}: {t}s")
    out.append(f"cost: ${r.get('cost_usd', 0):.4f}")
    out.append(f"papers: {r.get('papers', 0)}")
    return "\n".join(out)


async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/measure_search_latency.py <api_key> <query> [max_iter] [--restart]")
        sys.exit(1)
    api_key = sys.argv[1]
    query = sys.argv[2]
    max_iter = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 2
    if "--restart" in sys.argv:
        # 重启后端清空 in-memory 缓存
        print("[*] Restarting backend to clear in-memory cache...")
        subprocess.run(["cmd", "/c", "for /f", "tokens=5", "%a", "in", "('netstat", "-ano", "|", "findstr", ":8000", "^|", "findstr", "LISTENING')", "do", "taskkill", "/PID", "%a", "/F"],
                       shell=False, capture_output=True)
        time.sleep(3)
        proc = subprocess.Popen(
            ["python", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
            cwd=os.getcwd(),
            env={**os.environ, "OPEN_MODE": "true", "ENVIRONMENT": "dev", "LLM_PROVIDER": "minimax", "LLM_MOCK": "false", "API_MOCK": "false"},
        )
        time.sleep(8)
        # 测 health
        async with httpx.AsyncClient(timeout=10) as c:
            for _ in range(10):
                try:
                    r = await c.get("http://127.0.0.1:8000/api/v1/health")
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(1)
    r = await measure_stream(query, api_key, max_iter=max_iter)
    print(fmt_result(r))


if __name__ == "__main__":
    asyncio.run(main())
