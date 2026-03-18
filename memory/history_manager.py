"""BundleFabric — Execution history persistence (SQLite via aiosqlite)."""
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
import aiosqlite

HISTORY_DB = os.getenv("HISTORY_DB", "/app/data/history.db")
MAX_OUTPUT_LEN = 2000


async def init_db() -> None:
    """Initialize SQLite DB and create table if not exists."""
    db_path = Path(HISTORY_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(HISTORY_DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bundle_id TEXT NOT NULL,
                bundle_name TEXT,
                intent_text TEXT,
                goal TEXT,
                status TEXT,
                output TEXT,
                error_message TEXT,
                created_at REAL NOT NULL,
                duration_ms INTEGER
            )
        """)
        await db.commit()
    print(f"[History] DB initialized at {HISTORY_DB}")


async def record_execution(
    bundle_id: str,
    bundle_name: Optional[str],
    intent_text: str,
    goal: str,
    status: str,
    output: str,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> int:
    """Insert an execution record. Returns the new row id."""
    truncated_output = output[:MAX_OUTPUT_LEN] if output else ""
    async with aiosqlite.connect(HISTORY_DB) as db:
        cursor = await db.execute(
            """INSERT INTO executions
               (bundle_id, bundle_name, intent_text, goal, status, output, error_message, created_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bundle_id, bundle_name, intent_text[:500], goal[:500], status,
             truncated_output, error_message, time.time(), duration_ms),
        )
        await db.commit()
        return cursor.lastrowid


async def get_history(bundle_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Return last N executions, optionally filtered by bundle_id."""
    async with aiosqlite.connect(HISTORY_DB) as db:
        db.row_factory = aiosqlite.Row
        if bundle_id:
            cursor = await db.execute(
                "SELECT * FROM executions WHERE bundle_id=? ORDER BY created_at DESC LIMIT ?",
                (bundle_id, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM executions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_execution(exec_id: int) -> Optional[Dict[str, Any]]:
    """Return a single execution by id."""
    async with aiosqlite.connect(HISTORY_DB) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM executions WHERE id=?", (exec_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def search_history(q: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Full-text search on intent_text and goal fields."""
    pattern = f"%{q}%"
    async with aiosqlite.connect(HISTORY_DB) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM executions WHERE intent_text LIKE ? OR goal LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (pattern, pattern, min(limit, 200)),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_bundle_stats(bundle_id: str) -> Dict[str, Any]:
    """Return usage_count, last_executed timestamp, and success_rate for a bundle."""
    async with aiosqlite.connect(HISTORY_DB) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT COUNT(*) as total, MAX(created_at) as last_executed, "
            "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes "
            "FROM executions WHERE bundle_id=?",
            (bundle_id,),
        )
        row = await cursor.fetchone()
        total = row["total"] or 0
        last_executed = row["last_executed"]
        successes = row["successes"] or 0
        success_rate = round(successes / total, 4) if total > 0 else None
        return {
            "usage_count": total,
            "last_executed": last_executed,
            "success_rate": success_rate,
        }
