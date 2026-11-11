"""Router package for grouping FastAPI route handlers."""

from backend.routers import admin, auth

__all__ = ["auth", "admin"]
