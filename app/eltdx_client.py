from __future__ import annotations

from typing import Any

import httpx

from .models import AdapterError


class EltdxGateway:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        payload = {"id": 1, "method": method, "params": params}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/rpc", json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AdapterError(f"eltdx gateway request failed: {exc}") from exc
        if not body.get("ok"):
            error = body.get("error") or {}
            raise AdapterError(error.get("message", "eltdx gateway returned an error"))
        return body.get("result")


def result_rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if isinstance(result, dict):
        for key in ("rows", "quotes", "bars", "data", "items", "records"):
            value = result.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                nested = value.get("item")
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]
    return []
