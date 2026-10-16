from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.akshare_client import AkShareClient
from app.config import load_settings
from app.eltdx_client import EltdxGateway, result_rows
from app.normalizers import to_tdx_code

SHANGHAI = ZoneInfo("Asia/Shanghai")
Operation = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class BenchmarkOptions:
    symbol: str
    start: datetime
    end: datetime
    period: str


def build_cases(
    gateway: EltdxGateway,
    akshare_factory: Callable[[], AkShareClient],
    options: BenchmarkOptions,
) -> dict[str, dict[str, Operation]]:
    code = to_tdx_code(options.symbol)
    bar_start = options.start.isoformat()
    bar_end = options.end.isoformat()
    session_start = options.start.replace(hour=9, minute=30, second=0, microsecond=0)
    session_end = options.end.replace(hour=15, minute=0, second=0, microsecond=0)

    async def eltdx_realtime() -> Any:
        listed = result_rows(await gateway.call("codes.latest_stock_list", {}))
        codes = []
        for row in listed:
            full_code = row.get("full_code")
            raw_code = row.get("code")
            market = row.get("exchange") or row.get("market")
            if full_code:
                codes.append(full_code)
            elif raw_code and market:
                codes.append(f"{market.lower()}{raw_code}")
            elif raw_code:
                codes.append(raw_code)
        return await gateway.call("helpers.full_quotes", {"codes": list(dict.fromkeys(codes))})

    async def akshare_call(method: str, params: dict[str, Any]) -> Any:
        return await akshare_factory().call(method, params)

    daily_params = {
        "code": code, "period": "day", "count": 10,
        "start_time": options.start.isoformat(), "end_time": options.end.isoformat(),
    }
    minute_params = {
        "code": code, "period": options.period, "count": 240,
        "start_time": bar_start, "end_time": bar_end,
    }
    full_minute_params = {
        "code": code, "period": options.period, "count": 5000,
        "start_time": session_start.isoformat(), "end_time": session_end.isoformat(),
    }
    depth_params = {"codes": [code]}
    factor_params = {"code": code}
    finance_params = {"code": code, "report_type": "zcfzb"}

    def gateway_call(method: str, params: dict[str, Any]) -> Operation:
        return lambda: gateway.call(method, params)

    def akshare_method(method: str, params: dict[str, Any]) -> Operation:
        return lambda: akshare_call(method, params)

    return {
        "/realtime": {"ELTDX": eltdx_realtime, "AkShare": akshare_method("helpers.full_quotes", {"codes": []})},
        "/daily": {
            "ELTDX": gateway_call("bars.get", daily_params),
            "AkShare": akshare_method("bars.get", daily_params),
        },
        "/minute": {
            "ELTDX": gateway_call("bars.get", minute_params),
            "AkShare": akshare_method("bars.get", minute_params),
        },
        "/full_minute": {
            "ELTDX": gateway_call("bars.get", full_minute_params),
            "AkShare": akshare_method("bars.get", full_minute_params),
        },
        "/adj_factor": {
            "ELTDX": gateway_call("corporate.adjustment_factors", factor_params),
            "AkShare": akshare_method("corporate.adjustment_factors", factor_params),
        },
        "/financial": {
            "ELTDX": gateway_call("f10.finance_report", finance_params),
            "AkShare": akshare_method("f10.finance_report", finance_params),
        },
        "/depth5": {
            "ELTDX": gateway_call("quotes.get_depth", depth_params),
            "AkShare": akshare_method("quotes.get_depth", depth_params),
        },
    }


def row_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    return len(result_rows(result))

async def benchmark(cases: dict[str, dict[str, Operation]], repeats: int) -> dict[str, dict[str, dict[str, Any]]]:
    report: dict[str, dict[str, dict[str, Any]]] = {}
    for endpoint, sources in cases.items():
        report[endpoint] = {}
        for source, operation in sources.items():
            attempts: list[float] = []
            counts: list[int] = []
            errors: list[str] = []
            for _ in range(repeats):
                started = time.perf_counter()
                try:
                    result = await operation()
                    counts.append(row_count(result))
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                finally:
                    attempts.append(time.perf_counter() - started)
            report[endpoint][source] = {
                "successes": repeats - len(errors),
                "attempts_seconds": attempts,
                "median_seconds": statistics.median(attempts) if attempts else None,
                "record_counts": counts,
                "errors": errors,
            }
    return report


def print_report(report: dict[str, dict[str, dict[str, Any]]]) -> None:
    print(f"{'接口':<16} {'数据源':<10} {'成功':<8} {'中位耗时(s)':<14} {'记录数':<12} 错误")
    for endpoint, sources in report.items():
        for source, result in sources.items():
            median = result["median_seconds"]
            median_text = f"{median:.3f}" if median is not None else "-"
            counts = ",".join(str(count) for count in result["record_counts"]) or "-"
            error = result["errors"][0] if result["errors"] else "-"
            print(f"{endpoint:<16} {source:<10} {result['successes']:<8} {median_text:<14} {counts:<12} {error}")


def parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"无效的 ISO 日期时间：{value}") from exc


def parse_args() -> argparse.Namespace:
    defaults = load_settings()
    now = datetime.now(SHANGHAI).replace(second=0, microsecond=0)
    parser = argparse.ArgumentParser(description="对比 ELTDX 与 AkShare 的数据接口耗时")
    parser.add_argument("--gateway-url", default=defaults.gateway_url, help="ELTDX Gateway URL")
    parser.add_argument("--symbol", default="000001.SZ", help="证券代码，默认 000001.SZ")
    parser.add_argument("--start", type=parse_datetime, default=now - timedelta(minutes=30), help="ISO 开始时间")
    parser.add_argument("--end", type=parse_datetime, default=now, help="ISO 结束时间")
    parser.add_argument("--period", choices=("1m", "5m", "15m", "30m", "60m"), default="1m")
    parser.add_argument("--repeats", type=int, default=3, help="每个来源/接口的重复次数")
    parser.add_argument("--json", dest="json_path", type=Path, help="将完整测速结果写入 JSON 文件")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats 必须大于 0")
    if args.end <= args.start:
        parser.error("--end 必须晚于 --start")
    return args


async def run(args: argparse.Namespace) -> dict[str, dict[str, dict[str, Any]]]:
    options = BenchmarkOptions(args.symbol, args.start, args.end, args.period)
    gateway = EltdxGateway(args.gateway_url, timeout=30)
    cases = build_cases(gateway, lambda: AkShareClient(timeout=30), options)
    return await benchmark(cases, args.repeats)


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    print_report(report)
    if args.json_path:
        args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json_path}")


if __name__ == "__main__":
    main()
