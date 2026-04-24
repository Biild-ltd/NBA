"""Async PostgreSQL connection pool via Cloud SQL Python Connector.

Usage in services:
    pool = await get_pool()
    row  = await pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    rows = await pool.fetch("SELECT * FROM member_profiles")
    await pool.execute("UPDATE users SET role = $1 WHERE id = $2", role, user_id)

Call open_pool() on app startup and close_pool() on shutdown (wired in main.py lifespan).
"""
import logging

import asyncpg
from google.cloud.sql.connector import Connector

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_connector: Connector | None = None


async def open_pool() -> None:
    """Initialise the connection pool. Called once at app startup."""
    global _pool, _connector

    _connector = Connector()

    async def _getconn() -> asyncpg.Connection:
        return await _connector.connect_async(
            settings.CLOUD_SQL_INSTANCE,
            "asyncpg",
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            db=settings.DB_NAME,
        )

    _pool = await asyncpg.create_pool(
        connect=_getconn,
        min_size=2,
        max_size=10,
        command_timeout=30,
        server_settings={"application_name": "nba-backend"},
    )
    logger.info("PostgreSQL connection pool opened (instance=%s)", settings.CLOUD_SQL_INSTANCE)


async def close_pool() -> None:
    """Drain the pool and close the Cloud SQL connector. Called on shutdown."""
    global _pool, _connector
    if _pool:
        await _pool.close()
        _pool = None
    if _connector:
        _connector.close()
        _connector = None
    logger.info("PostgreSQL connection pool closed")


async def get_pool() -> asyncpg.Pool:
    """Return the live pool; raises RuntimeError if open_pool() was never called."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialised. Call open_pool() first.")
    return _pool
