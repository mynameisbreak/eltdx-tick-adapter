from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query

from .akshare_client import AkShareClient
from .config import load_settings
from .eltdx_client import EltdxGateway, result_rows
from .models import AdjFactorRequest, AdapterError, BarsRequest, DailyRequest, FinancialRequest
from .normalizers import (
    count_for_daily, count_for_period, normalize_adj_factor, normalize_bar,
    normalize_daily, normalize_depth5, normalize_realtime, to_tdx_code,
)

SETTINGS = load_settings()
GATEWAY_URL = SETTINGS.gateway_url


class FallbackGateway:
    def __init__(self, primary: EltdxGateway, fallback: AkShareClient | None) -> None:
        self.primary = primary
        self.fallback = fallback

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        primary_params = (
            {key: value for key, value in params.items() if key not in ("start_time", "end_time")}
            if method == "bars.get" else params
        )
        try:
            return await self.primary.call(method, primary_params)
        except AdapterError:
            if self.fallback is None:
                raise
            return await self.fallback.call(method, params)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="market-data tick adapter", version="0.3.0", lifespan=lifespan)
gateway = FallbackGateway(
    EltdxGateway(GATEWAY_URL, SETTINGS.gateway_timeout),
    AkShareClient(timeout=SETTINGS.akshare_timeout) if SETTINGS.akshare_enabled else None,
)


def gateway_error(exc: AdapterError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


def wall_clock(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def date_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if value is None:
        return None
    return str(value).replace("T", " ").split(" ", 1)[0]


def bar_in_range(row: dict[str, Any], start: datetime | None, end: datetime | None) -> bool:
    value = row.get("datetime") or row.get("date") or row.get("time")
    if value is None:
        return False
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("T", " ").replace("Z", "+00:00"))
        except ValueError:
            return False
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    start_wall = wall_clock(start)
    end_wall = wall_clock(end)
    return (start_wall is None or timestamp >= start_wall) and (end_wall is None or timestamp <= end_wall)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "gateway": GATEWAY_URL}


@app.get("/realtime")
async def realtime(symbols: str | None = Query(default=None)) -> dict[str, list[dict[str, Any]]]:
    del symbols  # The custom-source contract requires a full-market snapshot.
    try:
        listed = await gateway.call("codes.latest_stock_list", {})
        name_by_code: dict[str, str] = {}
        full_codes: list[str] = []
        for row in result_rows(listed):
            code = row.get("code")
            market = row.get("exchange") or row.get("market")
            if isinstance(code, str) and code.isdigit() and isinstance(market, str):
                full = f"{market.lower()}{code}"
            else:
                full = row.get("full_code") or code
            if not full:
                continue
            full_codes.append(full)
            name = row.get("name")
            if isinstance(name, str) and name:
                name_by_code[full.lower()] = name
        if isinstance(listed, list):
            full_codes.extend(code for code in listed if isinstance(code, str))
        full_codes = list(dict.fromkeys(full_codes))
        result = await gateway.call("helpers.full_quotes", {"codes": full_codes})
    except AdapterError as exc:
        raise gateway_error(exc) from exc
    data: list[dict[str, Any]] = []
    for row in result_rows(result):
        normalized = normalize_realtime(row, pct_unit="percent" if any(row.get(key) is not None for key in ("pct", "percent")) else "decimal")
        if normalized is None:
            continue
        if not normalized.get("name"):
            normalized["name"] = name_by_code.get(to_tdx_code(normalized["symbol"]).lower())
        data.append(normalized)
    return {"data": data}


async def bars(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    count = count_for_period(request.period, request.start_time, request.end_time)
    for symbol in request.symbols:
        try:
            # eltdx bars.get only accepts integer offset (start) + count;
            # start_time/end_time are not wire params. Fetch by count and filter
            # locally via bar_in_range below.
            params = {"code": to_tdx_code(symbol), "period": request.period, "count": count}
            result = await gateway.call("bars.get", params)
        except (AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data.extend(
            normalized for row in result_rows(result)
            if bar_in_range(row, request.start_time, request.end_time)
            and (normalized := normalize_bar(row, symbol))
        )
    return {"data": data}


@app.post("/daily")
async def daily(request: DailyRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    count = count_for_daily(request.start_time, request.end_time)
    for symbol in request.symbols:
        try:
            params = {"code": to_tdx_code(symbol), "period": "day", "count": count, "adjust": "none"}
            if request.start_time is not None:
                params["start_time"] = request.start_time
            if request.end_time is not None:
                params["end_time"] = request.end_time
            result = await gateway.call("bars.get", params)
        except (AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for row in result_rows(result):
            normalized = normalize_daily(row, symbol)
            if normalized is None:
                continue
            trade_date = normalized["date"]
            start_date = date_text(request.start_time)
            end_date = date_text(request.end_time)
            if start_date and trade_date < start_date:
                continue
            if end_date and trade_date > end_date:
                continue
            data.append(normalized)
    return {"data": data}


@app.post("/adj_factor")
async def adj_factor(request: AdjFactorRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    start_date = request.start_time.date().isoformat() if request.start_time else None
    for symbol in request.symbols:
        try:
            result = await gateway.call("corporate.adjustment_factors", {
                "code": to_tdx_code(symbol), **({"start_date": start_date} if start_date else {}),
            })
        except (AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        start_date = date_text(request.start_time)
        end_date = date_text(request.end_time)
        for row in result_rows(result):
            normalized = normalize_adj_factor(row, symbol)
            if normalized is None:
                continue
            if start_date and normalized["trade_date"] < start_date:
                continue
            if end_date and normalized["trade_date"] > end_date:
                continue
            data.append(normalized)
    return {"data": data}


@app.post("/financial")
async def financial(request: FinancialRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    for symbol in request.symbols:
        try:
            result = await gateway.call("f10.finance_report", {"code": to_tdx_code(symbol), "report_type": request.report_type})
        except (AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for row in result_rows(result):
            data.append({"symbol": symbol, **row})
    return {"data": data}


@app.post("/depth5")
async def depth5(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    try:
        result = await gateway.call("quotes.get_depth", {"codes": [to_tdx_code(symbol) for symbol in request.symbols]})
    except (AdapterError, ValueError) as exc:
        if isinstance(exc, AdapterError):
            raise gateway_error(exc) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = [normalized for row, symbol in zip(result_rows(result), request.symbols)
            if (normalized := normalize_depth5(row, symbol))]
    return {"data": data}


@app.post("/minute")
async def minute(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    return await bars(request)


@app.post("/full_minute")
async def full_minute(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    return await bars(request)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "3021")), reload=False)
