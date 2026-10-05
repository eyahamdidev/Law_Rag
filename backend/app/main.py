"""Web application entrypoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.config import REPO_ROOT

FRONTEND_DIR = REPO_ROOT / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tunisian Legal & Financial Assistant",
        summary="Scaffold for cited legal answers, fraud-signal review, and aid matching.",
        version="0.1.0",
    )
    app.include_router(api_router, prefix="/api")
    if FRONTEND_DIR.exists():
        app.mount(
            "/",
            StaticFiles(directory=Path(FRONTEND_DIR), html=True),
            name="frontend",
        )
    return app


app = create_app()
