from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .models import AdapterError
from .normalizers import from_tdx_code, to_tdx_code


class ProviderUnavailable(RuntimeError):
    pass


class StockSdkClient:
    def __init__(self, node: str = "node", bridge_path: str = "stock-sdk/bridge.mjs", timeout: float = 30.0) -> None:
        self.node = node
        self.bridge_path = Path(bridge_path).resolve()
        self.timeout = timeout

    async def _invoke(self, request: dict[str, Any]) -> Any:
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                self.node,
                str(self.bridge_path),
                cwd=self.bridge_path.parent,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(request).encode("utf-8")), timeout=self.timeout
            )
        except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            raise ProviderUnavailable(f"Stock SDK bridge failed: {exc}") from exc
        try:
            envelope = json.loads(stdout)
        except (UnicodeDecodeError, ValueError) as exc:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise ProviderUnavailable(f"Stock SDK bridge returned invalid JSON: {detail or exc}") from exc
        if not isinstance(envelope, dict) or process.returncode != 0 or not envelope.get("ok"):
            error = envelope.get("error", "bridge process failed") if isinstance(envelope, dict) else "invalid bridge response"
            raise ProviderUnavailable(f"Stock SDK error: {error}")
        return envelope.get("result")

    async def quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        result = await self._invoke({"op": "quotes.cn", "codes": codes})
        return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []

    async def daily(self, symbol: str, start_date: str | None, end_date: str | None) -> list[dict[str, Any]]:
        result = await self._invoke({
            "op": "kline.cn", "symbol": symbol,
            "options": {
                "period": "daily", "adjust": "",
                **({"startDate": start_date} if start_date else {}),
                **({"endDate": end_date} if end_date else {}),
            },
        })
        return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []

    async def minute(self, symbol: str, period: str, start_date: str | None, end_date: str | None) -> list[dict[str, Any]]:
        options: dict[str, Any] = {
            "period": period[:-1],
            **({"startDate": start_date} if start_date else {}),
            **({"endDate": end_date} if end_date else {}),
        }
        if period != "1m":
            options["adjust"] = ""
        result = await self._invoke({"op": "kline.cnMinute", "symbol": symbol, "options": options})
        return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []


class FuyaoRestClient:
    _FINANCIAL_PATHS = {
        "lrb": "income-statements", "income-statements": "income-statements",
        "zcfzb": "balance-sheets", "balance-sheets": "balance-sheets",
        "xjllb": "cash-flow-statements", "cash-flow-statements": "cash-flow-statements",
    }

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get(
                    f"{self.base_url}{path}", params=params, headers={"X-api-key": self.api_key}
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"Fuyao request failed: {exc}") from exc
        if not isinstance(body, dict):
            raise ProviderUnavailable("Fuyao returned an invalid response envelope")
        if body.get("code") != 0:
            raise ProviderUnavailable(f"Fuyao API error {body.get('code')}: {body.get('message', 'unknown error')}")
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise ProviderUnavailable("Fuyao response is missing data.item")
        return data

    async def snapshot(self, thscodes: list[str] | None = None) -> list[dict[str, Any]]:
        params = {"thscodes": ",".join(thscodes)} if thscodes else {"limit": 100, "offset": 0}
        data = await self._get("/api/a-share/prices/snapshot", params)
        rows = [row for row in data["item"] if isinstance(row, dict)]
        if thscodes:
            return rows
        total = data.get("total", len(rows))
        offset = len(rows)
        while offset < total:
            page = await self._get("/api/a-share/prices/snapshot", {"limit": 100, "offset": offset})
            page_rows = [row for row in page["item"] if isinstance(row, dict)]
            if not page_rows:
                break
            rows.extend(page_rows)
            offset += len(page_rows)
        return rows

    async def historical(self, thscode: str, start: int, end: int, adjust: str = "none") -> list[dict[str, Any]]:
        data = await self._get("/api/a-share/prices/historical", {
            "thscode": thscode, "interval": "1d", "start": start, "end": end, "adjust": adjust,
        })
        return [row for row in data["item"] if isinstance(row, dict)]

    async def financial(self, thscode: str, report_type: str, *, period: str = "annual", limit: int = 4,
                        start: int | None = None, end: int | None = None) -> list[dict[str, Any]]:
        endpoint = self._FINANCIAL_PATHS.get(report_type.lower())
        if endpoint is None:
            raise ProviderUnavailable(f"unsupported Fuyao financial report type: {report_type}")
        params: dict[str, Any] = {"thscode": thscode, "period": period}
        if start is not None and end is not None:
            params.update(start=start, end=end)
        elif start is None and end is None:
            params["limit"] = min(20, max(1, limit))
        else:
            raise ValueError("financial start and end must be provided together")
        data = await self._get(f"/api/a-share/financials/{endpoint}", params)
        return [row for row in data["item"] if isinstance(row, dict)]

    async def adjustment_events(self, thscode: str, start: str | None = None,
                                end: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"thscode": thscode}
        if start:
            params["from"] = start
        if end:
            params["to"] = end
        data = await self._get("/api/a-share/corporate-actions/adjustment-factors", params)
        return [row for row in data["item"] if isinstance(row, dict)]


@dataclass(frozen=True)
class SourceSettings:
    realtime: tuple[str, ...]
    daily: tuple[str, ...]
    minute: tuple[str, ...]
    depth5: tuple[str, ...]


class DataSourceRouter:
    def __init__(self, fuyao: FuyaoRestClient, stock_sdk: StockSdkClient, gateway: Any,
                 settings: SourceSettings) -> None:
        self.fuyao = fuyao
        self.stock_sdk = stock_sdk
        self.gateway = gateway
        self.settings = settings
        self._selected: dict[str, str] = {}

    async def realtime(self, symbols: list[str]) -> Any:
        selected = self._selected.get("realtime")
        sources = (selected,) if selected else self.settings.realtime
        for source in sources:
            try:
                if source == "fuyao":
                    return await self.fuyao.snapshot()
                if source == "stock_sdk":
                    return await self.stock_sdk.quotes(symbols)
                if source == "eltdx":
                    return await self.gateway.call("helpers.full_quotes", {"codes": symbols})
            except (ProviderUnavailable, AdapterError):
                if selected:
                    break
        if selected:
            for source in self.settings.realtime:
                if source == selected:
                    continue
                try:
                    if source == "fuyao":
                        return await self.fuyao.snapshot()
                    if source == "stock_sdk":
                        return await self.stock_sdk.quotes(symbols)
                    if source == "eltdx":
                        return await self.gateway.call("helpers.full_quotes", {"codes": symbols})
                except (ProviderUnavailable, AdapterError):
                    continue
        raise ProviderUnavailable("no realtime data source is available")

    async def daily(self, symbol: str, start: int | None, end: int | None,
                    start_date: str | None, end_date: str | None, count: int,
                    fuyao_key_available: bool) -> Any:
        last_error: AdapterError | None = None
        for source in self.settings.daily:
            try:
                if source == "fuyao" and fuyao_key_available and start is not None and end is not None:
                    return await self.fuyao.historical(symbol, start, end, adjust="none")
                if source == "stock_sdk":
                    return await self.stock_sdk.daily(symbol, start_date, end_date)
                if source == "eltdx":
                    return await self.gateway.call("bars.get", {
                        "code": to_tdx_code(symbol), "period": "day", "count": count, "adjust": "none",
                    })
            except AdapterError as exc:
                last_error = exc
            except ProviderUnavailable:
                continue
        if last_error is not None:
            raise last_error
        raise ProviderUnavailable("no daily data source is available")

    async def minute(self, symbol: str, period: str, start_date: str | None,
                     end_date: str | None, count: int) -> Any:
        last_error: AdapterError | None = None
        for source in self.settings.minute:
            try:
                if source == "stock_sdk":
                    return await self.stock_sdk.minute(symbol, period, start_date, end_date)
                if source == "eltdx":
                    return await self.gateway.call("bars.get", {
                        "code": to_tdx_code(symbol), "period": period, "count": count,
                    })
            except AdapterError as exc:
                last_error = exc
            except ProviderUnavailable:
                continue
        if last_error is not None:
            raise last_error
        raise ProviderUnavailable("no minute data source is available")

    async def depth5(self, symbols: list[str]) -> Any:
        last_error: AdapterError | None = None
        for source in self.settings.depth5:
            try:
                if source == "stock_sdk":
                    return await self.stock_sdk.quotes([to_tdx_code(symbol) for symbol in symbols])
                if source == "eltdx":
                    return await self.gateway.call("quotes.get_depth", {
                        "codes": [to_tdx_code(symbol) for symbol in symbols],
                    })
            except AdapterError as exc:
                last_error = exc
            except ProviderUnavailable:
                continue
        if last_error is not None:
            raise last_error
        raise ProviderUnavailable("no depth5 data source is available")

    async def select_realtime_source(self, symbols: list[str]) -> str:
        timings: list[tuple[float, str]] = []
        for source in self.settings.realtime:
            start = asyncio.get_running_loop().time()
            try:
                if source == "fuyao":
                    await self.fuyao.snapshot([from_tdx_code(item) or item for item in symbols[:10]])
                elif source == "stock_sdk":
                    await self.stock_sdk.quotes(symbols[:10])
                elif source == "eltdx":
                    await self.gateway.call("helpers.full_quotes", {"codes": symbols[:10]})
                else:
                    continue
            except Exception:
                continue
            timings.append((asyncio.get_running_loop().time() - start, source))
        if not timings:
            raise ProviderUnavailable("realtime source benchmark failed")
        self._selected["realtime"] = min(timings)[1]
        return self._selected["realtime"]
