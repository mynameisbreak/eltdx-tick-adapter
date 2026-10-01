from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from .eltdx_client import EltdxGateway, result_rows
from .models import AdapterError, BarsRequest
from .normalizers import count_for_period, normalize_bar, normalize_realtime, to_tdx_code


GATEWAY_URL = os.getenv("ELTDX_GATEWAY_URL", "http://127.0.0.1:8000")
GATEWAY_TIMEOUT = float(os.getenv("ELTDX_GATEWAY_TIMEOUT", "30"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="eltdx tick-stock-panel adapter", version="0.1.0", lifespan=lifespan)
gateway = EltdxGateway(GATEWAY_URL, GATEWAY_TIMEOUT)


def gateway_error(exc: AdapterError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "gateway": GATEWAY_URL}


@app.get("/realtime")
async def realtime(symbols: str | None = Query(default=None)) -> dict[str, list[dict[str, Any]]]:
    del symbols  # The custom-source contract requires a full-market snapshot.
    try:
        codes = await gateway.call("codes.all_stocks", {})
        full_codes = [
            row.get("full_code") or row.get("code")
            for row in result_rows(codes)
            if row.get("full_code") or row.get("code")
        ]
        if isinstance(codes, list):
            full_codes.extend(code for code in codes if isinstance(code, str))
        full_codes = list(dict.fromkeys(full_codes))
        result = await gateway.call("helpers.full_quotes", {"codes": full_codes})
    except AdapterError as exc:
        raise gateway_error(exc) from exc
    data = [normalized for row in result_rows(result) if (normalized := normalize_realtime(row))]
    return {"data": data}


async def bars(request: BarsRequest) -> dict[str, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    count = count_for_period(request.period, request.start_time, request.end_time)
    for symbol in request.symbols:
        try:
            result = await gateway.call(
                "bars.get",
                {"code": to_tdx_code(symbol), "period": request.period, "count": count},
            )
        except (AdapterError, ValueError) as exc:
            if isinstance(exc, AdapterError):
                raise gateway_error(exc) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data.extend(
            normalized
            for row in result_rows(result)
            if (normalized := normalize_bar(row, symbol))
        )
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
