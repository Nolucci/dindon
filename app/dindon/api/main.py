"""The web application: API, live events, and the interface. One process also runs the inbox and the collector."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from dindon import __version__
from dindon.api.auth import COOKIE, LIFETIME, Auth, require_session
from dindon.api.hub import Hub
from dindon.api.imports import router as imports_router
from dindon.api.routes import router
from dindon.collector.job import ImportJobs
from dindon.config import Settings, load_settings
from dindon.db import connect
from dindon.health import database_report, ollama_report
from dindon.ingest.inbox import scan_once

log = logging.getLogger("dindon")

# The page may only load what the application itself serves: no font, script or image from anywhere else
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                           "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


class Login(BaseModel):
    password: str


async def inbox_loop(settings: Settings) -> None:
    """Imports what is dropped in inbox/, every couple of seconds."""
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                conn = await asyncio.to_thread(connect, settings.database_url)
                conn.autocommit = True
            await asyncio.to_thread(scan_once, conn, settings.inbox_dir, settings.archive_dir)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("inbox: %s, retrying", type(error).__name__)
            conn = None
        await asyncio.sleep(2)


def create_app(settings: Settings | None = None, background: bool = True) -> FastAPI:
    """`background=False` leaves out the inbox and the collector (the tests drive them themselves)."""
    settings = settings or load_settings()
    auth = Auth(settings.password)  # refuses to start without a password
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=8, open=False, name="dindon",
                          kwargs={"autocommit": True, "row_factory": dict_row})
    hub = Hub(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(pool.open, True, 30)
        tasks = [asyncio.create_task(hub.run())]
        if background:
            tasks.append(asyncio.create_task(inbox_loop(settings)))
            if settings.discord_token and settings.guild_ids and settings.collector_enabled:
                from dindon.collector.watch import Collector

                app.state.collector = Collector(settings)
                tasks.append(asyncio.create_task(app.state.collector.run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(pool.close)

    app = FastAPI(title="Dindon", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings, app.state.auth, app.state.pool, app.state.hub, app.state.collector = settings, auth, pool, hub, None
    app.state.imports = ImportJobs(settings)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(("/api", "/events")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> dict:
        # Only counts, never any content: this endpoint needs no password
        try:
            with connect(settings.database_url) as conn:
                database = database_report(conn)
        except Exception:
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ok", "version": __version__, "database": database, "ollama": ollama_report(settings.ollama_url)}

    @app.post("/api/login")
    def login(body: Login, response: Response) -> dict:
        if not auth.check_password(body.password):
            raise HTTPException(status_code=401, detail="wrong password")
        response.set_cookie(COOKIE, auth.make_token(), max_age=LIFETIME, httponly=True, samesite="strict", path="/")
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/session")
    def session(request: Request) -> dict:
        return {"authenticated": auth.verify(request.cookies.get(COOKIE))}

    @app.get("/events", dependencies=[Depends(require_session)])
    async def events() -> StreamingResponse:
        queue = hub.subscribe()

        async def stream():
            try:
                yield 'retry: 3000\n\ndata: {"type":"hello"}\n\n'
                while True:
                    try:
                        yield f"data: {await asyncio.wait_for(queue.get(), 15)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.include_router(router)
    app.include_router(imports_router)

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return "<p>The interface is not built yet: run <code>make web</code> (or rebuild the Docker image).</p>"

    return app
