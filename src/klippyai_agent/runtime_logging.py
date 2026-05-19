from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from klippyai_agent.settings import Settings

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_runtime_logging(settings: Settings) -> Path | None:
    level_name = settings.agent_log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    file_path: Path | None = None
    try:
        candidate = settings.agent_log_path()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            candidate,
            maxBytes=settings.agent_log_max_bytes,
            backupCount=settings.agent_log_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
        file_path = candidate
    except OSError as exc:
        logging.basicConfig(level=level, format=_FORMAT)
        logging.getLogger("klippyai_agent.logging").warning(
            "Could not open KlippyAI log file under %s: %s. Falling back to stderr/journal only.",
            settings.host_logs_dir(),
            exc,
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "klippyai_agent"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    logger = logging.getLogger("klippyai_agent.logging")
    if file_path is not None:
        logger.info("Runtime logging configured at %s", file_path)
    else:
        logger.warning("Runtime logging configured without a file sink.")
    return file_path
