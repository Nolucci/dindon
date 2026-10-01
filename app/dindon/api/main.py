"""The web application. Phase 0: the health check only."""
from fastapi import FastAPI, HTTPException

from dindon import __version__
from dindon.config import Settings, load_settings
from dindon.db import connect
from dindon.health import database_report, ollama_report


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Dindon", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict:
        # Only counts, never any content: this endpoint needs no password
        try:
            with connect(settings.database_url) as conn:
                database = database_report(conn)
        except Exception:
            raise HTTPException(status_code=503, detail="database unavailable")
        return {
            "status": "ok",
            "version": __version__,
            "database": database,
            "ollama": ollama_report(settings.ollama_url),
        }

    return app
