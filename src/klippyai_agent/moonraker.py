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
        payload = await self._request("GET", "/server/info")
        if isinstance(payload, dict):
            return payload
        raise MoonrakerError("Moonraker returned an unexpected /server/info payload.")

    async def get_printer_info(self) -> dict[str, Any]:
        payload = await self._request("GET", "/printer/info")
        if isinstance(payload, dict):
            return payload
        raise MoonrakerError("Moonraker returned an unexpected /printer/info payload.")

    async def list_printer_objects(self) -> list[str]:
        payload = await self._request("GET", "/printer/objects/list")
        if isinstance(payload, dict) and isinstance(payload.get("objects"), list):
            return [str(item) for item in payload["objects"]]
        if isinstance(payload, list):
            return [str(item) for item in payload]
        raise MoonrakerError("Moonraker returned an unexpected /printer/objects/list payload.")

    async def query_printer_objects(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        payload = await self._request("POST", "/printer/objects/query", json={"objects": objects})
        if isinstance(payload, dict):
            status = payload.get("status")
            if isinstance(status, dict):
                return status
            return payload
        raise MoonrakerError("Moonraker returned an unexpected /printer/objects/query payload.")

    async def get_system_info(self) -> dict[str, Any]:
        payload = await self._request("GET", "/machine/system_info")
        if isinstance(payload, dict):
            system_info = payload.get("system_info")
            if isinstance(system_info, dict):
                return system_info
            return payload
        raise MoonrakerError("Moonraker returned an unexpected /machine/system_info payload.")

    async def get_update_status(self) -> dict[str, Any]:
        payload = await self._request("GET", "/machine/update/status")
        if isinstance(payload, dict):
            return payload
        raise MoonrakerError("Moonraker returned an unexpected /machine/update/status payload.")

    async def list_serial_devices(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/machine/peripherals/serial")
        if isinstance(payload, dict) and isinstance(payload.get("serial_devices"), list):
            return [item for item in payload["serial_devices"] if isinstance(item, dict)]
        raise MoonrakerError("Moonraker returned an unexpected /machine/peripherals/serial payload.")

    async def list_usb_devices(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/machine/peripherals/usb")
        if isinstance(payload, dict) and isinstance(payload.get("usb_devices"), list):
            return [item for item in payload["usb_devices"] if isinstance(item, dict)]
        raise MoonrakerError("Moonraker returned an unexpected /machine/peripherals/usb payload.")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = await self._client.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MoonrakerError(f"Moonraker request failed: {exc}") from exc

        payload = response.json()
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        if isinstance(payload, dict):
            return payload
        raise MoonrakerError(f"Moonraker returned an unexpected payload for {path}.")
