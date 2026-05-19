from __future__ import annotations

import logging

import uvicorn

from klippyai_agent.app import create_app
from klippyai_agent.runtime_logging import configure_runtime_logging
from klippyai_agent.settings import get_settings

logger = logging.getLogger("klippyai_agent.bootstrap")


def main() -> None:
    settings = get_settings()
    settings.ensure_directories()
    log_path = configure_runtime_logging(settings)
    logger.info(
        "Starting KlippyAI host=%s port=%s root_path=%s moonraker_url=%s read_only=%s log_path=%s",
        settings.host,
        settings.port,
        settings.root_path or "/",
        settings.moonraker_url,
        not settings.enable_write_actions,
        log_path or "stderr-only",
    )
    uvicorn.run(
        "klippyai_agent.app:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        log_config=None,
        access_log=True,
    )


if __name__ == "__main__":
    main()
