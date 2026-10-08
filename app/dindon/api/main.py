"""The web application: API, live events, and the interface. One process also runs the inbox and the collector."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from dindon import __version__
from dindon.analysis.job import AnalysisJobs
from dindon.analysis import helpers
from dindon.api.activity import router as activity_router
from dindon.api.analysis import router as analysis_router
from dindon.api.reread import router as reread_router
from dindon.analysis.reread import RereadJobs
from dindon.api.auth import COOKIE, LIFETIME, Auth, require_session
from dindon.api.debates import router as debates_router
from dindon.api.automation import router as automation_router
from dindon.api.background import start_background_tasks
from dindon.api.hub import Hub
from dindon.api.discord_card import router as discord_card_router
from dindon.api.discord_map import router as discord_map_router
from dindon.api.imports import router as imports_router
from dindon.api.invite import router as invite_router
from dindon.api.performance import router as performance_router
from dindon.api.positions import router as positions_router
from dindon.api.privacy import router as privacy_router
from dindon.api.routes import router
from dindon.api.system import router as system_router
from dindon.collector.job import ImportJobs
from dindon.config import Settings, load_settings
from dindon.db import connect
from dindon.health import database_report, ollama_report

# The page may only load what the application itself serves: no font, script or image from anywhere else
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                           "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


ACTIVITY_FRAME_ANCESTORS = "frame-ancestors https://discord.com https://*.discord.com https://*.discordsays.com"


def _is_activity_page(request: Request) -> bool:
    """Discord opens an Activity at the root of its address with a `frame_id`: that request gets the map (activity.html), everything else gets the interface."""
    return request.url.path == "/" and "frame_id" in request.query_params


class Login(BaseModel):
    password: str


def _session_router(auth: Auth) -> APIRouter:
    """Logging in and out, and whether the cookie of the request is a session (the only routes of the API that need no session)."""
    router = APIRouter(prefix="/api")

    @router.post("/login")
    def login(body: Login, response: Response) -> dict:
        if not auth.check_password(body.password):
            raise HTTPException(status_code=401, detail="wrong password")
        response.set_cookie(COOKIE, auth.make_token(), max_age=LIFETIME, httponly=True, samesite="strict", path="/")
        return {"ok": True}

    @router.post("/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/session")
    def session(request: Request) -> dict:
        return {"authenticated": auth.verify(request.cookies.get(COOKIE))}

    return router


def _health_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict:
        # Only counts, never any content: this endpoint needs no password
        try:
            with connect(settings.database_url) as conn:
                database = database_report(conn)
        except Exception:
            raise HTTPException(status_code=503, detail="database unavailable") from None
        return {"status": "ok", "version": __version__, "database": database, "ollama": ollama_report(settings.ollama_url)}

    return router


def _live_router(hub: Hub) -> APIRouter:
    """The stream of events (Server-Sent Events) that lights up the links of the map as the messages arrive."""
    router = APIRouter(dependencies=[Depends(require_session)])

    @router.get("/events")
    async def events() -> StreamingResponse:
        queue = hub.subscribe()

        async def stream():
            try:
                yield 'retry: 3000\n\ndata: {"type":"hello"}\n\n'
                while True:
                    try:
                        yield f"data: {await asyncio.wait_for(queue.get(), 15)}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router


def _add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if _is_activity_page(request):                          # the one page that Discord puts in a frame: the map, nothing else
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY.replace("frame-ancestors 'none'", ACTIVITY_FRAME_ANCESTORS)
            del response.headers["X-Frame-Options"]
        if request.url.path.startswith(("/api", "/events")):
            response.headers["Cache-Control"] = "no-store"
        return response


def _mount_interface(app: FastAPI, settings: Settings) -> None:
    if settings.web_dir.is_dir():
        @app.get("/", include_in_schema=False)
        def root(request: Request) -> FileResponse:
            return FileResponse(settings.web_dir / ("activity.html" if _is_activity_page(request) else "index.html"))

        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
        return

    @app.get("/", response_class=HTMLResponse)
    def not_built() -> str:
        return "<p>The interface is not built yet: run <code>make web</code> (or rebuild the Docker image).</p>"


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
        with pool.connection() as conn:
            configured = helpers.load(conn)
            shares = helpers.load_shares(conn)
        if configured is not None:
            app.state.analysis.configure_helpers(configured, shares)
        tasks = [asyncio.create_task(hub.run())]
        if background:
            tasks += start_background_tasks(app, settings)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(pool.close)

    # No schema of the API either (/openapi.json): nobody needs it without a session, and nothing in the interface reads it
    app = FastAPI(title="Dindon", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings, app.state.auth, app.state.pool, app.state.hub, app.state.collector = settings, auth, pool, hub, None
    app.state.imports = ImportJobs(settings)
    app.state.analysis = AnalysisJobs(settings)
    app.state.reread = RereadJobs(settings, app.state.analysis)

    _add_security_headers(app)
    for api_router in (_health_router(settings), _session_router(auth), _live_router(hub), router, imports_router, invite_router, analysis_router, reread_router, system_router,
                       privacy_router, positions_router, performance_router, automation_router, debates_router, discord_map_router, discord_card_router, activity_router):
        app.include_router(api_router)
    _mount_interface(app, settings)
    return app
