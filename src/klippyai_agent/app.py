from __future__ import annotations

import os
from contextlib import asynccontextmanager
from importlib.resources import files

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from klippyai_agent.container import AppContainer, build_container
from klippyai_agent.schemas import BootstrapResponse, ChatRequest, ChatResponse, UiSessionResponse
from klippyai_agent.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_directories()
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

    package_root = files("klippyai_agent")
    templates = Jinja2Templates(directory=str(package_root.joinpath("templates")))
    static_dir = str(package_root.joinpath("static"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db)) as checkpointer:
            container = build_container(settings, checkpointer)
            app.state.container = container
            yield
            await container.aclose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        root_path=settings.root_path.rstrip("/"),
    )
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    @app.get("/", response_class=HTMLResponse)
    async def standalone(request: Request) -> HTMLResponse:
        container = _get_container(request)
        ui_session = await container.chat_service.create_ui_session()
        return templates.TemplateResponse(
            request=request,
            name="standalone.html",
            context={
                "embed_path": ui_session.embed_path,
                "mainsail_href": "/",
            },
        )

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
    async def embed(session: str, request: Request) -> HTMLResponse:
        container = _get_container(request)
        if not container.sessions.exists(session):
            raise HTTPException(status_code=403, detail="Invalid or expired session.")

        api_base = f"{settings.root_path.rstrip('/')}/api" if settings.root_path else "/api"
        return templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": session,
                "api_base": api_base,
            },
        )

    return app


def _get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if not container:
        raise RuntimeError("Application container is not initialized.")
    return container
