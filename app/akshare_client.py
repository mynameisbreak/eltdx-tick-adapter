from __future__ import annotations

import asyncio
import math
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

from .models import AdapterError


REPORT_TYPES = {"zcfzb": "资产负债表", "lrb": "利润表", "xjllb": "现金流量表"}


def clean(value: Any) -> Any:
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()[:10]
    return value.item() if hasattr(value, "item") else value


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(key): clean(value) for key, value in row.items()} for row in frame.to_dict("records")]


SHANGHAI = ZoneInfo("Asia/Shanghai")


def local_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(SHANGHAI).replace(tzinfo=None)
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return local_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError as exc:
            raise ValueError(f"invalid bar time: {value!r}") from exc
    raise ValueError(f"invalid bar time: {value!r}")


def bar_window(params: dict[str, Any], count: int, fallback_days: int) -> tuple[datetime, datetime]:
    today = datetime.now(SHANGHAI).date()
    end_value = params.get("end_time")
    end = (
        local_datetime(end_value)
        if end_value is not None
        else datetime.combine(today, datetime.max.time()).replace(microsecond=0)
    )
    start_value = params.get("start_time")
    start = (
        local_datetime(start_value)
        if start_value is not None
        else datetime.combine(end.date(), datetime.min.time()) - timedelta(days=fallback_days)
    )
    return start, end


class AkShareClient:
    def __init__(self, api: Any = ak, timeout: float = 30.0) -> None:
        self.api = api
        self.timeout = timeout
        self._snapshot: list[dict[str, Any]] = []
        self._snapshot_at = 0.0

    async def _run(self, function: Any, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            frame = await asyncio.wait_for(asyncio.to_thread(function, **kwargs), self.timeout)
            if not isinstance(frame, pd.DataFrame):
                raise ValueError("AkShare did not return a DataFrame")
            return records(frame)
        except (Exception, asyncio.TimeoutError) as exc:
            raise AdapterError(f"AkShare request failed: {type(exc).__name__}: {exc}") from exc

    async def _spot(self) -> list[dict[str, Any]]:
        if not self._snapshot or time.monotonic() - self._snapshot_at > 15:
            rows = await self._run(self.api.stock_zh_a_spot_tx)
            if not rows:
                raise AdapterError("AkShare returned no realtime quotes")
            self._snapshot = rows
            self._snapshot_at = time.monotonic()
        return self._snapshot

    async def call(self, method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if method in ("codes.latest_stock_list", "helpers.full_quotes"):
            spot = await self._spot()
            if method == "codes.latest_stock_list":
                return [{"full_code": row["code"], "name": row.get("name")} for row in spot]
            codes = set(params.get("codes", []))
            quotes = []
            for row in spot:
                code = row.get("code")
                if not code or codes and code not in codes:
                    continue
                try:
                    price, pct = float(row["zxj"]), float(row["zdf"])
                    prev = price / (1 + pct / 100)
                except (ValueError, TypeError, ZeroDivisionError):
                    continue
                quotes.append({"code": code, "name": row.get("name"), "price": price,
                               "pre_close_price": prev, "pct": pct,
                               "volume": float(row["volume"]) if row.get("volume") is not None else None,
                               "amount": float(row["turnover"]) if row.get("turnover") is not None else None})
            return quotes

        code = params.get("code", "")
        symbol = code[2:] if isinstance(code, str) and code[:2] in ("sh", "sz", "bj") else code
        if method == "bars.get":
            period = params.get("period", "day")
            count = int(params.get("count", 800))
            if period == "day":
                start, end = bar_window(params, count, count * 2 + 10)
                rows = await self._run(
                    self.api.stock_zh_a_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="",
                )
                field = "日期"
            elif period in ("1m", "5m", "15m", "30m", "60m"):
                start, end = bar_window(params, count, max(5, count // 240 * 2 + 5))
                rows = await self._run(
                    self.api.stock_zh_a_hist_min_em,
                    symbol=symbol,
                    start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
                    period=period[:-1],
                    adjust="",
                )
                field = "时间"
            else:
                raise AdapterError(f"unsupported AkShare bar period: {period}")
            return [{"code": code, "date" if period == "day" else "datetime": row[field],
                     "open": row.get("开盘"), "high": row.get("最高"), "low": row.get("最低"),
                     "close": row.get("收盘"), "volume": row.get("成交量"), "amount": row.get("成交额")}
                    for row in rows[-count:]]

        if method == "quotes.get_depth":
            result = []
            for full_code in params["codes"]:
                rows = await self._run(self.api.stock_bid_ask_em, symbol=full_code[2:])
                values = {row["item"]: row["value"] for row in rows}
                def levels(prefix: str) -> list[dict[str, float]]:
                    return [{"price": float(values[f"{prefix}_{i}"]), "volume": float(values[f"{prefix}_{i}_vol"])}
                            for i in range(1, 6) if values.get(f"{prefix}_{i}") is not None
                            and values.get(f"{prefix}_{i}_vol") is not None]
                result.append({"code": full_code, "buy_levels": levels("buy"), "sell_levels": levels("sell")})
            return result

        if method == "corporate.adjustment_factors":
            rows = await self._run(self.api.stock_zh_a_daily, symbol=code, adjust="qfq-factor")
            start = params.get("start_date")
            return [{"date": row["date"], "qfq_scale": float(row["qfq_factor"])} for row in rows
                    if row.get("qfq_factor") is not None and (not start or row["date"] >= start)]

        if method == "f10.finance_report":
            report = REPORT_TYPES.get(params.get("report_type"))
            if report is None:
                raise AdapterError(f"unsupported AkShare report type: {params.get('report_type')}")
            return await self._run(self.api.stock_financial_report_sina, stock=code, symbol=report)
        raise AdapterError(f"unsupported AkShare method: {method}")
