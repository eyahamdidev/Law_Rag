"""Web application entrypoint."""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.config import REPO_ROOT, settings

FRONTEND_DIR = REPO_ROOT / "frontend"
logger = logging.getLogger(__name__)


def _warm_up() -> None:
    """Load the embedder and reranker once (about 45 s on a GTX 1050), off the request path."""
    try:
        from app.modules.rag.retrieval.hybrid import search

        search("capital minimum société anonyme", k=1)
        logger.info("retrieval models loaded")
    except Exception as error:  # a missing index must not stop the API
        logger.warning("warm-up skipped: %s", error)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env != "test":
        threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tunisian Legal & Financial Assistant",
        summary="Multi-agent assistant with cited answers from Tunisian official texts.",
        version="0.2.0",
        lifespan=lifespan,
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
