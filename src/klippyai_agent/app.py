from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from klippyai_agent.container import AppContainer, build_container
from klippyai_agent.schemas import BootstrapResponse, ChatRequest, ChatResponse, UiSessionResponse
from klippyai_agent.settings import get_settings

logger = logging.getLogger("klippyai_agent.app")


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
            "Application startup printer_data_root=%s host_logs_dir=%s",
            settings.printer_data_root,
            settings.host_logs_dir(),
        )
        container = build_container(settings)
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
