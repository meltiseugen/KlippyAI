from __future__ import annotations

import uvicorn

from klippyai_agent.app import create_app
from klippyai_agent.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "klippyai_agent.app:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
    )


if __name__ == "__main__":
    main()

