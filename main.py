"""Entrypoint. The app is assembled in api/app.py (factory + routers)."""
from api.app import app

__all__ = ["app"]
