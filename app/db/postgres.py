"""Async PostgreSQL connection pool via Cloud SQL Unix socket.

On Cloud Run, Cloud SQL sockets are mounted at /cloudsql/<INSTANCE_CONNECTION_NAME>
when --add-cloudsql-instances is set. asyncpg connects via that Unix domain socket.

Usage in services:
    pool = await get_pool()
    row  = await pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    rows = await pool.fetch("SELECT * FROM member_profiles")
    await pool.execute("UPDATE users SET role = $1 WHERE id = $2", role, user_id)

Call open_pool() on app startup and close_pool() on shutdown (wired in main.py lifespan).
"""
import logging

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def open_pool() -> None:
    """Initialise the connection pool. Called once at app startup."""
    global _pool

    _pool = await asyncpg.create_pool(
        host=f"/cloudsql/{settings.CLOUD_SQL_INSTANCE}",
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        min_size=2,
        max_size=10,
        command_timeout=30,
        server_settings={"application_name": "nba-backend"},
    )
    logger.info("PostgreSQL connection pool opened (instance=%s)", settings.CLOUD_SQL_INSTANCE)


async def close_pool() -> None:
    """Drain the pool. Called on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
    logger.info("PostgreSQL connection pool closed")


async def get_pool() -> asyncpg.Pool:
    """Return the live pool; raises RuntimeError if open_pool() was never called."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialised. Call open_pool() first.")
    return _pool
