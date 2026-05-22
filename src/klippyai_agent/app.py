from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from klippyai_agent.container import AppContainer, build_container
from klippyai_agent.schemas import BootstrapResponse, ChatRequest, ChatResponse, UiSessionResponse
from klippyai_agent.settings import get_settings

logger = logging.getLogger("klippyai_agent.app")

_SHELL_ICON_SVGS = {
    "dashboard": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"></rect>'
        '<rect x="13.5" y="3.5" width="7" height="4.5" rx="1.5"></rect>'
        '<rect x="13.5" y="10.5" width="7" height="10" rx="1.5"></rect>'
        '<rect x="3.5" y="13.5" width="7" height="7" rx="1.5"></rect>'
        "</svg>"
    ),
    "webcam": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<rect x="4" y="6.5" width="16" height="11" rx="2.5"></rect>'
        '<circle cx="12" cy="12" r="3.5"></circle>'
        '<path d="M8 19.5h8"></path>'
        "</svg>"
    ),
    "console": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M5 7.5l5 4.5-5 4.5"></path>'
        '<path d="M12.5 17h6.5"></path>'
        "</svg>"
    ),
    "files": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M7 3.5h7l4 4v13H7z"></path>'
        '<path d="M14 3.5v4h4"></path>'
        '<path d="M9 13.5h6"></path>'
        '<path d="M9 17h6"></path>'
        "</svg>"
    ),
    "viewer": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M4.5 8.5h15"></path>'
        '<path d="M4.5 15.5h15"></path>'
        '<path d="M7.5 5.5v13"></path>'
        '<path d="M16.5 5.5v13"></path>'
        "</svg>"
    ),
    "history": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M5 7.5H2.5V5"></path>'
        '<path d="M3 7.5A9 9 0 1 1 6 18"></path>'
        '<path d="M12 8v4.5l3 2"></path>'
        "</svg>"
    ),
    "klippyai": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M7 8.5a5 5 0 0 1 10 0v4.5a5 5 0 0 1-10 0z"></path>'
        '<circle cx="10" cy="12" r="1"></circle>'
        '<circle cx="14" cy="12" r="1"></circle>'
        '<path d="M9.5 15h5"></path>'
        '<path d="M12 3v2.5"></path>'
        '<path d="M6.5 6 5 4.5"></path>'
        '<path d="M17.5 6 19 4.5"></path>'
        "</svg>"
    ),
    "machine": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<circle cx="12" cy="12" r="3"></circle>'
        '<path d="M12 4v2.5"></path>'
        '<path d="M12 17.5V20"></path>'
        '<path d="M4 12h2.5"></path>'
        '<path d="M17.5 12H20"></path>'
        '<path d="M6.3 6.3 8 8"></path>'
        '<path d="M16 16l1.7 1.7"></path>'
        '<path d="M16 8l1.7-1.7"></path>'
        '<path d="M6.3 17.7 8 16"></path>'
        "</svg>"
    ),
}

_SHELL_NAV_BLUEPRINT = (
    ("dashboard", "Dashboard", "/"),
    ("webcam", "Webcam", "/webcam"),
    ("console", "Console", "/console"),
    ("files", "G-Code Files", "/files"),
    ("viewer", "G-Code Viewer", "/gcodeviewer"),
    ("history", "History", "/history"),
    ("klippyai", "KlippyAI", None),
    ("machine", "Machine", "/machine"),
)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_directories()
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(package_dir / "templates"))
    static_dir = package_dir / "static"
    embed_css = (static_dir / "embed.css").read_text(encoding="utf-8")
    embed_js = (static_dir / "embed.js").read_text(encoding="utf-8")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "Application startup checkpoint_db=%s printer_data_root=%s host_logs_dir=%s",
            settings.checkpoint_db,
            settings.printer_data_root,
            settings.host_logs_dir(),
        )
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db)) as checkpointer:
            container = build_container(settings, checkpointer)
            app.state.container = container
            logger.info("Application startup complete.")
            try:
                yield
            finally:
                logger.info("Application shutdown started.")
                await container.aclose()
                logger.info("Application shutdown complete.")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        root_path=settings.root_path.rstrip("/"),
    )
    app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")

    root_base = settings.root_path.rstrip("/") if settings.root_path else ""
    api_base = f"{root_base}/api" if root_base else "/api"
    shell_nav_items = _build_shell_nav(root_base)

    @app.get("/", response_class=HTMLResponse)
    async def standalone(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": "",
                "api_base": api_base,
                "embed_css": embed_css,
                "embed_js": embed_js,
                "shell_nav_items": shell_nav_items,
                "shell_home_href": "/",
                "shell_klippyai_href": f"{root_base}/" if root_base else "/",
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/direct", response_class=HTMLResponse)
    async def direct(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": "",
                "api_base": api_base,
                "embed_css": embed_css,
                "embed_js": embed_js,
                "shell_nav_items": shell_nav_items,
                "shell_home_href": "/",
                "shell_klippyai_href": f"{root_base}/" if root_base else "/",
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, object]:
        container = _get_container(request)
        return {
            "status": "ok",
            "moonraker_reachable": await container.moonraker.ping(),
        }

    @app.post("/api/ui-sessions", response_model=UiSessionResponse, name="create_ui_session")
    async def create_ui_session(request: Request) -> UiSessionResponse:
        container = _get_container(request)
        return await container.chat_service.create_ui_session()

    @app.get("/api/bootstrap", response_model=BootstrapResponse)
    async def bootstrap(session_id: str, request: Request) -> BootstrapResponse:
        container = _get_container(request)
        try:
            return await container.chat_service.bootstrap(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        container = _get_container(request)
        try:
            return await container.chat_service.chat(payload)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/embed", response_class=HTMLResponse)
    async def embed(request: Request, session: str | None = None) -> HTMLResponse:
        if session:
            logger.info("Serving embed UI with hinted session_id=%s; client will bootstrap a fresh session if needed", session)
        response = templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": session or "",
                "api_base": api_base,
                "embed_css": embed_css,
                "embed_js": embed_js,
                "shell_nav_items": shell_nav_items,
                "shell_home_href": "/",
                "shell_klippyai_href": f"{root_base}/" if root_base else "/",
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


def _get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if not container:
        raise RuntimeError("Application container is not initialized.")
    return container


def _build_shell_nav(root_base: str) -> list[dict[str, Any]]:
    klippyai_href = f"{root_base}/" if root_base else "/"
    items: list[dict[str, Any]] = []
    for icon_name, label, href in _SHELL_NAV_BLUEPRINT:
        resolved_href = klippyai_href if href is None else href
        items.append(
            {
                "label": label,
                "href": resolved_href,
                "icon_svg": _SHELL_ICON_SVGS[icon_name],
                "active": False,
            }
        )
    return items
