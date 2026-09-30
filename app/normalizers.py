from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any


_PERIOD_COUNTS = {"1m": 240, "5m": 48, "15m": 16, "30m": 8, "60m": 4}


def to_tdx_code(symbol: str) -> str:
    code, market = symbol.upper().split(".", 1)
    prefix = {"SZ": "sz", "SH": "sh", "BJ": "bj"}.get(market)
    if prefix is None or not code.isdigit():
        raise ValueError(f"unsupported symbol: {symbol}")
    return f"{prefix}{code}"


def from_tdx_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.lower()
    for prefix, market in (("sz", "SZ"), ("sh", "SH"), ("bj", "BJ")):
        if raw.startswith(prefix) and raw[len(prefix):].isdigit():
            return f"{raw[len(prefix):].zfill(6)}.{market}"
    return value if "." in value else None


def number(row: dict[str, Any], *names: str) -> float | int | None:
    for name in names:
        value = row.get(name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def normalize_realtime(row: dict[str, Any]) -> dict[str, Any] | None:
    symbol = from_tdx_code(row.get("symbol") or row.get("code") or row.get("ts_code"))
    last = number(row, "last_price", "price", "last", "close")
    prev = number(row, "prev_close", "pre_close", "yesterday_close")
    if symbol is None or last is None or prev is None:
        return None
    result: dict[str, Any] = {
        "symbol": symbol,
        "name": row.get("name") or row.get("stock_name"),
        "last_price": last,
        "prev_close": prev,
        "open": number(row, "open", "open_price"),
        "high": number(row, "high", "high_price"),
        "low": number(row, "low", "low_price"),
        "volume": number(row, "volume", "vol"),
        "amount": number(row, "amount", "amt", "turnover"),
    }
    pct = number(row, "change_pct", "pct", "percent")
    result["change_pct"] = pct / 100 if pct is not None and abs(pct) > 1 else pct
    return result


def normalize_bar(row: dict[str, Any], fallback_symbol: str) -> dict[str, Any] | None:
    symbol = from_tdx_code(row.get("symbol") or row.get("code") or row.get("ts_code")) or fallback_symbol
    timestamp = row.get("datetime") or row.get("date") or row.get("time")
    if timestamp is None:
        return None
    if isinstance(timestamp, datetime):
        dt = timestamp
    else:
        text = str(timestamp).replace("T", " ").replace("Z", "")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    return {
        "symbol": symbol,
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "open": number(row, "open"),
        "high": number(row, "high"),
        "low": number(row, "low"),
        "close": number(row, "close", "last"),
        "volume": number(row, "volume", "vol"),
        "amount": number(row, "amount", "amt", "turnover"),
    }


def count_for_period(period: str, start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None or end <= start:
        return _PERIOD_COUNTS[period]
    minutes = max(1, int((end - start).total_seconds() / 60))
    return min(5000, max(_PERIOD_COUNTS[period], minutes // int(period[:-1])))
