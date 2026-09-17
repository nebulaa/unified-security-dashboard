"""FastAPI app entrypoint.

Build the verifier eagerly at startup so misconfigurations (— `dev`
backend outside `local`) crash the process before serving any request.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_admin_dlq import router as admin_dlq_router
from app.api.routes_admin_ownership import router as admin_ownership_router
from app.api.routes_admin_pollers import router as admin_pollers_router
from app.api.routes_components import router as components_router
from app.api.routes_coverage import router as coverage_router
from app.api.routes_feedback import router as feedback_router
from app.api.routes_findings import router as findings_router
from app.api.routes_internal import router as internal_router
from app.api.routes_me import router as me_router
from app.api.routes_metrics import router as metrics_router
from app.api.routes_scanners import router as scanners_router
from app.api.routes_teams import router as teams_router
from app.api.routes_tokens import router as tokens_router
from app.core.config import get_settings
from app.core.identity import build_verifier


def create_app() -> FastAPI:
    settings = get_settings()
    build_verifier(settings)  # fail-fast at boot

    app = FastAPI(title="secdb API", version="0.1.0")
    app.include_router(me_router)
    app.include_router(feedback_router)
    app.include_router(tokens_router)
    app.include_router(findings_router)
    app.include_router(metrics_router)
    app.include_router(coverage_router)
    app.include_router(scanners_router)
    app.include_router(teams_router)
    app.include_router(components_router)
    app.include_router(internal_router)
    app.include_router(admin_dlq_router)
    app.include_router(admin_pollers_router)
    app.include_router(admin_ownership_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    return app


app = create_app()
