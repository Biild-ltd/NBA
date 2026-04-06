"""Singleton rate-limiter instance shared across all routers.

Importing from app.main would create circular imports because main.py imports
routers. Keeping the limiter here breaks that cycle.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
