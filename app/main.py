from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query

from .config import load_settings, resolve_fuyao_api_key
from .eltdx_client import EltdxGateway, result_rows
from .models import AdjFactorRequest, AdapterError, BarsRequest, DailyRequest, FinancialRequest
from .providers import DataSourceRouter, FuyaoRestClient, ProviderUnavailable, SourceSettings, StockSdkClient
from .normalizers import (
    count_for_daily,
    count_for_period,
    normalize_adj_factor,
    normalize_bar,
    normalize_daily,
    normalize_depth5,
    normalize_realtime,
    to_tdx_code,
)


SETTINGS = load_settings()
GATEWAY_URL = SETTINGS.gateway_url
GATEWAY_TIMEOUT = SETTINGS.gateway_timeout


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="market-data tick adapter", version="0.2.0", lifespan=lifespan)
gateway = EltdxGateway(GATEWAY_URL, GATEWAY_TIMEOUT)
fuyao = FuyaoRestClient(
    SETTINGS.fuyao_base_url,
    resolve_fuyao_api_key(SETTINGS),
    SETTINGS.fuyao_timeout,
)
stock_sdk = StockSdkClient(
    SETTINGS.stock_sdk_node,
    SETTINGS.stock_sdk_bridge,
    SETTINGS.stock_sdk_timeout,
)
realtime_source: str | None = None


def gateway_error(exc: AdapterError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


def source_router(dataset: str = "realtime") -> DataSourceRouter:
    api_key_set = bool(resolve_fuyao_api_key(SETTINGS))
    sources_by_dataset = {
        "realtime": SETTINGS.realtime_sources,
        "daily": SETTINGS.daily_sources,
        "minute": SETTINGS.minute_sources,
        "depth5": SETTINGS.depth5_sources,
    }

    def usable(items: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            source
            for source in items
            if (source != "fuyao" or (SETTINGS.fuyao_enabled and api_key_set))
            and (source != "stock_sdk" or SETTINGS.stock_sdk_enabled)
        )

    return DataSourceRouter(
        fuyao,
        stock_sdk,
        gateway,
        SourceSettings(
            realtime=usable(sources_by_dataset[dataset]),
            daily=usable(sources_by_dataset["daily"]),
            minute=usable(sources_by_dataset["minute"]),
            depth5=usable(sources_by_dataset["depth5"]),
        ),
    )


def wall_clock(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def timestamp_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(value.timestamp() * 1000)
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
    global realtime_source
    del symbols  # The custom-source contract requires a full-market snapshot.
    router = source_router()
    try:
        use_external_provider = any(source in {"fuyao", "stock_sdk"} for source in router.settings.realtime)
        try:
            listed = await gateway.call("codes.latest_stock_list", {})
        except AdapterError:
            if not use_external_provider:
                raise
            listed = []
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
        if SETTINGS.benchmark_on_start and realtime_source is None:
            try:
                realtime_source = await router.select_realtime_source(full_codes)
            except ProviderUnavailable:
                pass
        if realtime_source is not None:
            router._selected["realtime"] = realtime_source
        result = await router.realtime(full_codes)
    except (AdapterError, ProviderUnavailable) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data: list[dict[str, Any]] = []
    symbol_by_code = {
        (code[2:] if code.lower().startswith(("sz", "sh", "bj")) else code).zfill(6): code
        for code in full_codes
        if isinstance(code, str)
    }
    for row in result_rows(result):
        code = row.get("code")
        symbol = symbol_by_code.get(str(code).zfill(6)) if code is not None else None
        normalized = normalize_realtime(
            {**row, "symbol": row.get("symbol") or symbol, "name": row.get("name") or (name_by_code.get(symbol) if symbol else None)},
            pct_unit="percent"
            if any(row.get(key) is not None for key in ("pct", "percent", "price_change_ratio_pct", "changePercent"))
            else "decimal",
        )
        if normalized is None:
            continue
        if not normalized.get("name"):
            normalized["name"] = name_by_code.get(to_tdx_code(normalized["symbol"]).lower())
        data.append(normalized)
    return {"data": data}

def sdk_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    local = wall_clock(value) or value
    return local.strftime("%Y-%m-%d %H:%M")
async def bars(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    count = count_for_period(request.period, request.start_time, request.end_time)
    router = source_router("minute")
    for symbol in request.symbols:
        try:
            rows = await router.minute(
                symbol, request.period, sdk_datetime(request.start_time), sdk_datetime(request.end_time), count
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (ProviderUnavailable, AdapterError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        data.extend(
            normalized
            for row in result_rows(rows)
            if bar_in_range(row, request.start_time, request.end_time)
            and (normalized := normalize_bar(row, symbol))
        )
    return {"data": data}


@app.post("/daily")
async def daily(request: DailyRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    count = count_for_daily(request.start_time, request.end_time)
    start_date = date_text(request.start_time)
    end_date = date_text(request.end_time)
    router = source_router("daily")
    for symbol in request.symbols:
        try:
            rows = await router.daily(
                symbol,
                timestamp_ms(request.start_time) if request.start_time else None,
                timestamp_ms(request.end_time) if request.end_time else None,
                start_date.replace("-", "") if start_date else None,
                end_date.replace("-", "") if end_date else None,
                count,
                bool(resolve_fuyao_api_key(SETTINGS)),
            )
        except (ProviderUnavailable, AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=502 if isinstance(exc, ProviderUnavailable) else 400, detail=str(exc)) from exc
        for row in result_rows(rows):
            normalized = normalize_daily(row, symbol)
            if normalized is None:
                continue
            trade_date = normalized["date"]
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
            result = await gateway.call(
                "corporate.adjustment_factors",
                {
                    "code": to_tdx_code(symbol),
                    **({"start_date": start_date} if start_date else {}),
                },
            )
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


FUYAO_FINANCIAL_TYPES = {
    "lrb", "income-statements", "zcfzb", "balance-sheets", "xjllb", "cash-flow-statements"
}


@app.post("/financial")
async def financial(request: FinancialRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    for symbol in request.symbols:
        try:
            if (
                request.report_type in FUYAO_FINANCIAL_TYPES
                and SETTINGS.fuyao_enabled
                and bool(resolve_fuyao_api_key(SETTINGS))
            ):
                rows = await fuyao.financial(symbol, request.report_type)
            else:
                rows = await gateway.call(
                    "f10.finance_report",
                    {"code": to_tdx_code(symbol), "report_type": request.report_type},
                )
        except ProviderUnavailable:
            try:
                rows = await gateway.call(
                    "f10.finance_report",
                    {"code": to_tdx_code(symbol), "report_type": request.report_type},
                )
            except AdapterError as exc:
                raise gateway_error(exc) from exc
        except (AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for row in result_rows(rows):
            data.append({"symbol": symbol, **row})
    return {"data": data}


@app.post("/depth5")
async def depth5(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    router = source_router("depth5")
    try:
        rows = await router.depth5(request.symbols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ProviderUnavailable, AdapterError) as exc:
        if isinstance(exc, AdapterError):
            raise gateway_error(exc) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data = [
        normalized
        for row, symbol in zip(result_rows(rows), request.symbols)
        if (normalized := normalize_depth5(row, symbol))
    ]
    return {"data": data}


@app.post("/minute")
async def minute(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    return await bars(request)


@app.post("/full_minute")
async def full_minute(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    return await bars(request)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "3021")),
        reload=False,
    )
