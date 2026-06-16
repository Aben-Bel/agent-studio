"""Application factory. Keeps the entrypoint thin: discover plugins, connect any
env database, build the app, and mount the routers. All HTTP handlers live in
api/routers/* (thin) and delegate to core/ services - so 8 people can add
endpoints in separate router files without colliding in one giant main.py."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import cfg
from core.discovery import discover
from core.util import log
from connectors import datastore
from api.routers import capabilities, data, chat, export


def create_app() -> FastAPI:
    discover()   # auto-register everything in agents/ tools/ skills/ connectors/ mcp/ pipeline/

    # Connect a database given via env up front; runtime URLs come in via /connect-db.
    if cfg.database_url:
        try:
            info = datastore.connect_db(cfg.database_url, "default")
            log.info("connected env database as '%s' (%s)", info["name"], info["dialect"])
        except Exception as e:
            log.warning("DATABASE_URL could not be connected: %s", e)

    # Make the uploads bucket accept browser direct (presigned) uploads. Without a
    # bucket CORS policy the browser's preflight PUT is blocked. Best-effort: S3 may
    # be unset or creds expired - that must NOT stop the app (the direct-POST upload
    # fallback still works). Idempotent, so safe on every boot.
    if cfg.s3_bucket:
        try:
            from connectors.s3 import s3
            s3.ensure_cors()
            log.info("ensured S3 CORS on bucket '%s' for browser uploads", cfg.s3_bucket)
        except Exception as e:
            log.warning("could not set S3 bucket CORS (browser uploads may fall back "
                        "to direct POST): %s", e)

    app = FastAPI(
        title=cfg.app_title,
        description="Auto-discovered agents, tools, skills, MCP servers and pipeline "
                    "stages. Every capability is a self-declaring file. Frontend builds "
                    "against this OpenAPI spec.",
        version="1.0.0",
    )
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins,
                       allow_methods=["*"], allow_headers=["*"])

    app.include_router(capabilities.router, tags=["platform"])
    app.include_router(data.router, tags=["data"])
    app.include_router(chat.router, tags=["investigations"])
    app.include_router(export.router, tags=["output"])
    return app


app = create_app()
