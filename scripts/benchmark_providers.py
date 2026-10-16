from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SYMBOL = "000001.SZ"
TDX_CODE = "sz000001"
START_MS = 1780272000000
END_MS = 1780358400000
SOURCE_KEYS = {
    "realtime": "realtime_sources",
    "daily": "daily_sources",
    "minute": "minute_sources",
    "depth5": "depth5_sources",
    "financial": "financial_sources",
    "adj_factor": "adj_factor_sources",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_toml(path: Path) -> dict[str, Any]:
    import tomllib

    with path.open("rb") as handle:
        return tomllib.load(handle)


def api_key(config: dict[str, Any]) -> str:
    fuyao = config.get("fuyao", {})
    env_name = fuyao.get("api_key_env", "HITHINK_FINANCE_API_KEY")
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    try:
        return Path(fuyao.get("api_key_file", ".secrets/fuyao_api_key")).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def request_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fuyao_call(config: dict[str, Any], path: str, params: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    key = api_key(config)
    if not key:
        raise RuntimeError("Fuyao key is not configured")
    base = config.get("fuyao", {}).get("base_url", "https://fuyao.aicubes.cn").rstrip("/")
    query = urllib.parse.urlencode(params)
    body = request_json(f"{base}{path}?{query}", {"X-api-key": key}, timeout)
    if body.get("code") != 0:
        raise RuntimeError(f"Fuyao business code {body.get('code')}")
    data = body.get("data") or {}
    items = data.get("item")
    if not isinstance(items, list):
        raise RuntimeError("Fuyao response has no item list")
    return [item for item in items if isinstance(item, dict)]


def eltdx_call(config: dict[str, Any], method: str, params: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    base = config.get("eltdx", {}).get("url", "http://127.0.0.1:8000").rstrip("/")
    payload = json.dumps({"id": 1, "method": method, "params": params}).encode("utf-8")
    request = urllib.request.Request(f"{base}/rpc", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"ELTDX error: {(body.get('error') or {}).get('message', 'unknown')}")
    result = body.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("rows", "quotes", "bars", "data", "items", "records"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def stock_call(config: dict[str, Any], operation: str, request: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    stock = config.get("stock_sdk", {})
    if not stock.get("enabled", True):
        raise RuntimeError("Stock SDK is disabled")
    node = os.getenv("STOCK_SDK_NODE", stock.get("node", "node"))
    bridge = Path(os.getenv("STOCK_SDK_BRIDGE", stock.get("bridge", "stock-sdk/bridge.mjs")))
    if not bridge.is_absolute():
        bridge = Path.cwd() / bridge
    payload = json.dumps({"op": operation, **request})
    try:
        completed = subprocess.run(
            [node, str(bridge)], input=payload, text=True, capture_output=True,
            timeout=timeout, cwd=str(bridge.parent), check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Stock SDK bridge unavailable: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise RuntimeError("Stock SDK bridge returned an error")
    try:
        body = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Stock SDK bridge returned invalid JSON") from exc
    if not body.get("ok"):
        raise RuntimeError("Stock SDK operation failed")
    result = body.get("result")
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def operations(config: dict[str, Any], timeout: float) -> dict[str, dict[str, Any]]:
    return {
        "fuyao": {
            "realtime": lambda: fuyao_call(config, "/api/a-share/prices/snapshot", {"thscodes": SYMBOL}, timeout),
            "daily": lambda: fuyao_call(config, "/api/a-share/prices/historical", {"thscode": SYMBOL, "interval": "1d", "start": START_MS, "end": END_MS, "adjust": "none"}, timeout),
            "financial": lambda: fuyao_call(config, "/api/a-share/financials/balance-sheets", {"thscode": SYMBOL, "period": "annual", "limit": 1}, timeout),
            "adj_factor": lambda: fuyao_call(config, "/api/a-share/corporate-actions/adjustment-factors", {"thscode": SYMBOL}, timeout),
        },
        "stock_sdk": {
            "realtime": lambda: stock_call(config, "quotes.cn", {"codes": [TDX_CODE]}, timeout),
            "daily": lambda: stock_call(config, "kline.cn", {"symbol": SYMBOL, "options": {"period": "daily", "adjust": "", "startDate": "20260901", "endDate": "20261015"}}, timeout),
            "minute": lambda: stock_call(config, "kline.cnMinute", {"symbol": SYMBOL, "options": {"period": "1", "startDate": "2026-10-15 09:30", "endDate": "2026-10-15 10:00"}}, timeout),
            "depth5": lambda: stock_call(config, "quotes.cn", {"codes": [TDX_CODE]}, timeout),
        },
        "eltdx": {
            "realtime": lambda: eltdx_call(config, "helpers.full_quotes", {"codes": [TDX_CODE]}, timeout),
            "daily": lambda: eltdx_call(config, "bars.get", {"code": TDX_CODE, "period": "day", "count": 30, "adjust": "none"}, timeout),
            "minute": lambda: eltdx_call(config, "bars.get", {"code": TDX_CODE, "period": "1m", "count": 30}, timeout),
            "depth5": lambda: eltdx_call(config, "quotes.get_depth", {"codes": [TDX_CODE]}, timeout),
            "financial": lambda: eltdx_call(config, "f10.finance_report", {"code": TDX_CODE, "report_type": "zcfzb"}, timeout),
            "adj_factor": lambda: eltdx_call(config, "corporate.adjustment_factors", {"code": TDX_CODE}, timeout),
        },
    }


def run_benchmark(config: dict[str, Any], rounds: int, timeout: float) -> list[dict[str, Any]]:
    providers = operations(config, timeout)
    rows: list[dict[str, Any]] = []
    for dataset in SOURCE_KEYS:
        for provider, provider_ops in providers.items():
            operation = provider_ops.get(dataset)
            if operation is None:
                rows.append({"timestamp": now_iso(), "dataset": dataset, "provider": provider, "ok": False, "rows": 0, "elapsed_ms": None, "error": "unsupported"})
                continue
            for attempt in range(1, rounds + 1):
                started = time.perf_counter()
                try:
                    result = operation()
                    rows.append({"timestamp": now_iso(), "dataset": dataset, "provider": provider, "attempt": attempt, "ok": True, "rows": len(result), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "error": None})
                except Exception as exc:
                    rows.append({"timestamp": now_iso(), "dataset": dataset, "provider": provider, "attempt": attempt, "ok": False, "rows": 0, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "error": str(exc)[:240]})
    return rows


def choose_order(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    routing = config.get("routing", {})
    for dataset, key in SOURCE_KEYS.items():
        grouped: dict[str, list[float]] = {}
        for row in rows:
            if row["dataset"] == dataset and row.get("ok") and row.get("rows", 0) > 0:
                grouped.setdefault(row["provider"], []).append(float(row["elapsed_ms"]))
        ranked = sorted(grouped, key=lambda provider: statistics.median(grouped[provider]))
        current = list(routing.get(key, []))
        result[dataset] = ranked + [provider for provider in current if provider not in ranked]
    return result


def apply_orders(path: Path, orders: dict[str, list[str]]) -> None:
    text = path.read_text(encoding="utf-8")
    for dataset, key in SOURCE_KEYS.items():
        if not routing_key_exists(text, key):
            continue
        replacement = f"{key} = [" + ", ".join(json.dumps(item) for item in orders[dataset]) + "]"
        pattern = rf"(?m)^{re.escape(key)}\s*=.*$"
        text, count = re.subn(pattern, replacement, text)
        if count != 1:
            raise RuntimeError(f"could not update {key}")
    path.write_text(text, encoding="utf-8")


def routing_key_exists(text: str, key: str) -> bool:
    return re.search(rf"(?m)^{re.escape(key)}\s*=", text) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark market data providers and optionally update routing order.")
    parser.add_argument("--config", default="config/data_sources.toml")
    parser.add_argument("--log-dir", default="log")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    config_path = Path(args.config)
    config = load_toml(config_path)
    rows = run_benchmark(config, args.rounds, args.timeout)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    detail_path = log_dir / f"provider-benchmark-{stamp}.jsonl"
    summary_path = log_dir / f"provider-benchmark-{stamp}.summary.json"
    with detail_path.open("w", encoding="utf-8") as detail:
        for row in rows:
            detail.write(json.dumps(row, ensure_ascii=False) + "\n")
    orders = choose_order(rows, config)
    summary = {"timestamp": now_iso(), "rounds": args.rounds, "orders": orders, "detail_log": str(detail_path), "rows": rows}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.apply:
        apply_orders(config_path, orders)
        summary["applied"] = True
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"detail_log": str(detail_path), "summary": str(summary_path), "orders": orders, "applied": args.apply}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
