"""Tests for H8: cache table must not store query text.

The audit found that ``backend/utils/cache.py``'s ``search_cache`` table
stored the raw query string in a ``query TEXT NOT NULL`` column. Anyone
with read access to the SQLite file (backups, CI artifacts, accidental
upload) could dump every user's search history and the corresponding
report. The fix:

  1. Drop the ``query`` column.
  2. Migrate the existing schema in place (idempotent — runs at every
     ``_init_db()`` call).
  3. ``set_cached`` no longer writes the query.

These tests verify:
  * Schema no longer has the ``query`` column after first ``_init_db()``.
  * Round-trip write/read still works (cache hit returns the same
    ``response_json``).
  * The SQLite file's text payload for a cached entry does NOT contain
    the original query string (privacy check).
  * A second ``_init_db()`` call is still idempotent.
  * Migration: if we manually pre-create the OLD schema with the ``query``
    column, ``_init_db()`` must drop that column while preserving all
    other data.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Per-test isolated cache DB (so we never touch the dev backend's cache)
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_cache_db(monkeypatch, tmp_path: Path):
    """Redirect the cache module to a fresh SQLite file in tmp_path.

    This is critical — the dev ``backend/.cache/search_cache.sqlite``
    might have a known-good payload we don't want to disturb, and we
    also want full schema control (e.g. to inject the OLD schema and
    verify migration).
    """
    db_path = tmp_path / "test_search_cache.sqlite"
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir(exist_ok=True)

    # Re-bind the module-level cache path constants
    from backend.utils import cache as cache_mod
    monkeypatch.setattr(cache_mod, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cache_mod, "_DB", db_path)
    # Also clear any cached _init_db side effect (it was run on import of
    # other modules). Reload not necessary — we just call _init_db again.
    return db_path


# ---------------------------------------------------------------------------
# 1. New schema: no `query` column
# ---------------------------------------------------------------------------

def test_new_schema_has_no_query_column(temp_cache_db: Path) -> None:
    """First _init_db() on a fresh file creates the table WITHOUT `query`."""
    from backend.utils import cache as cache_mod

    cache_mod._init_db()

    conn = sqlite3.connect(str(temp_cache_db))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(search_cache)").fetchall()]
    finally:
        conn.close()

    assert "query" not in cols, (
        f"H8 FAIL: cache table still has `query` column. Columns: {cols}"
    )
    # And the required columns ARE present
    for required in ("query_hash", "response_json", "cost_usd", "tokens", "created_at"):
        assert required in cols, f"Missing required column: {required}"


# ---------------------------------------------------------------------------
# 2. Round-trip still works
# ---------------------------------------------------------------------------

def test_roundtrip_works_without_query(temp_cache_db: Path) -> None:
    """set_cached + get_cached round-trip the response correctly."""
    from backend.utils import cache as cache_mod

    response = {
        "report": "## Sample\nHello world.",
        "ranked_papers": [{"title": "P1"}],
        "total_cost_usd": 0.12,
    }
    cache_mod.set_cached("transformer attention is all you need", 2, 1.0, response, 0.12, 200)
    result = cache_mod.get_cached("transformer attention is all you need", 2, 1.0)

    assert result is not None, "cache miss after set_cached"
    cached_response, cost, tokens = result
    assert cached_response == response
    assert cost == 0.12
    assert tokens == 200


# ---------------------------------------------------------------------------
# 3. Privacy check: raw SQLite payload must NOT contain the query text
# ---------------------------------------------------------------------------

def test_raw_sqlite_payload_does_not_contain_query(temp_cache_db: Path) -> None:
    """Open the cache SQLite file directly and assert the query string
    is not present anywhere in any cell of the cached row.

    This is the privacy check — even if a write-capable attacker
    replaces the response_json, the query history is no longer
    recoverable from the file.
    """
    from backend.utils import cache as cache_mod

    secret_query = "patient_genome_sequence_HLAB*15:02_alert(1)"
    response = {"report": "ok", "ranked_papers": []}
    cache_mod.set_cached(secret_query, 2, 1.0, response, 0.01, 10)

    # Read the raw file bytes — both header and rows
    raw_bytes = temp_cache_db.read_bytes()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")

    assert secret_query not in raw_text, (
        "H8 FAIL: query text is leaked into the SQLite file (even as part of "
        "a row's TEXT cells)."
    )
    # Also check the indexed blob columns explicitly
    conn = sqlite3.connect(str(temp_cache_db))
    try:
        for col in ("query_hash", "response_json", "cost_usd", "tokens", "created_at"):
            for val in conn.execute(f"SELECT {col} FROM search_cache").fetchall():
                val_str = str(val).encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
                assert secret_query not in val_str, (
                    f"H8 FAIL: query text leaked into column {col!r} (value={val!r})"
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Idempotency
# ---------------------------------------------------------------------------

def test_init_db_is_idempotent(temp_cache_db: Path) -> None:
    """Calling _init_db() multiple times must be safe (no DROP, no errors)."""
    from backend.utils import cache as cache_mod

    cache_mod._init_db()
    cache_mod._init_db()
    cache_mod._init_db()

    conn = sqlite3.connect(str(temp_cache_db))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(search_cache)").fetchall()]
    finally:
        conn.close()

    assert "query" not in cols
    assert "query_hash" in cols


# ---------------------------------------------------------------------------
# 5. Migration: pre-existing OLD schema (with `query` column) gets migrated
# ---------------------------------------------------------------------------

def test_migration_drops_query_column(temp_cache_db: Path) -> None:
    """Simulate an OLD cache.db with the legacy `query` column and a
    pre-existing row. _init_db() must:
      - create search_cache_new (no query column)
      - copy data over (without query)
      - drop the old table
      - rename new → search_cache
      - PRESERVE query_hash + response_json + cost_usd + tokens + created_at
    """
    # Manually create the OLD schema + insert a row
    conn = sqlite3.connect(str(temp_cache_db))
    conn.execute(
        """
        CREATE TABLE search_cache (
            query_hash TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            response_json TEXT NOT NULL,
            cost_usd REAL NOT NULL,
            tokens INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO search_cache VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "abc123",
            "this query text must be GONE after migration",
            '{"report": "preserved"}',
            0.42,
            314,
            1700000000.0,
        ),
    )
    conn.commit()
    conn.close()

    # Run the migration
    from backend.utils import cache as cache_mod
    cache_mod._init_db()

    # Verify the schema
    conn = sqlite3.connect(str(temp_cache_db))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(search_cache)").fetchall()]
        assert "query" not in cols, (
            f"H8 FAIL: migration did not drop `query` column. Columns: {cols}"
        )

        # The pre-existing row should still be there (without the query)
        row = conn.execute(
            "SELECT query_hash, response_json, cost_usd, tokens, created_at "
            "FROM search_cache WHERE query_hash=?",
            ("abc123",),
        ).fetchall()
        assert len(row) == 1, f"Expected 1 migrated row, got {len(row)}"
        qhash, response_json, cost, tokens, created_at = row[0]
        assert qhash == "abc123"
        assert response_json == '{"report": "preserved"}'
        assert cost == 0.42
        assert tokens == 314
        assert created_at == 1700000000.0

        # The original query text is no longer accessible via SQL.
        # (Note: SQLite's freelist may still hold the old bytes in the
        # file — purging that requires VACUUM. For the privacy threat
        # model (an attacker with a SQLite client), the relevant check
        # is that the LIVE table no longer exposes the query.)
        rows = conn.execute(
            "SELECT * FROM search_cache"
        ).fetchall()
        flat = " ".join(str(cell) for row in rows for cell in row)
        assert "this query text must be GONE after migration" not in flat, (
            "H8 FAIL: original query text is still recoverable from the "
            "search_cache table after migration"
        )

        # Run a VACUUM and re-check the file content (production deployments
        # should also VACUUM after migration to scrub freelist bytes).
        conn.execute("VACUUM")
        conn.close()
        raw_text = temp_cache_db.read_bytes().decode("utf-8", errors="ignore")
        assert "this query text must be GONE after migration" not in raw_text, (
            "H8 FAIL: original query text still in the SQLite file even "
            "after VACUUM (file should not contain the old query bytes)"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Re-migrate safety: after migration, _init_db() must not try to migrate again
# ---------------------------------------------------------------------------

def test_post_migration_init_db_is_noop(temp_cache_db: Path) -> None:
    """After migration runs once, subsequent _init_db() calls must not
    try to migrate (the `query` column is gone)."""
    from backend.utils import cache as cache_mod

    # Manually create old schema with a row
    conn = sqlite3.connect(str(temp_cache_db))
    conn.execute(
        """
        CREATE TABLE search_cache (
            query_hash TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            response_json TEXT NOT NULL,
            cost_usd REAL NOT NULL,
            tokens INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO search_cache VALUES (?, ?, ?, ?, ?, ?)",
        ("q1", "old query", "{}", 0.1, 10, 1.0),
    )
    conn.commit()
    conn.close()

    # First call: migrate
    cache_mod._init_db()
    # Second call: should be a no-op
    cache_mod._init_db()

    # Row should still be there
    conn = sqlite3.connect(str(temp_cache_db))
    try:
        rows = conn.execute("SELECT query_hash FROM search_cache").fetchall()
        assert rows == [("q1",)]
    finally:
        conn.close()
