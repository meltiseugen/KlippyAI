from __future__ import annotations

from typing import Any

import httpx


class MoonrakerError(RuntimeError):
    pass


class MoonrakerClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            await self.get_server_info()
        except MoonrakerError:
            return False
        return True

    async def get_server_info(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/server/info")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MoonrakerError(f"Moonraker request failed: {exc}") from exc

        payload = response.json()
        if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], dict):
            return payload["result"]
        if isinstance(payload, dict):
            return payload
        raise MoonrakerError("Moonraker returned an unexpected payload.")

