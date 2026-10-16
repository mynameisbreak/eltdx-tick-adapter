from datetime import datetime, timedelta

import pytest

from scripts.benchmark_data_sources import BenchmarkOptions, benchmark, build_cases


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, method: str, params: dict) -> list[dict]:
        self.calls.append(method)
        if method == "codes.latest_stock_list":
            return [{"full_code": "sz000001"}]
        return [{"code": "sz000001", "date": "2026-10-15"}]


class FakeAkShare:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict) -> list[dict]:
        self.calls.append((method, params))
        return [{"code": "sz000001", "date": "2026-10-15"}]


@pytest.mark.asyncio
async def test_benchmark_covers_all_data_endpoints_for_both_sources() -> None:
    gateway, akshare = FakeGateway(), FakeAkShare()
    end = datetime(2026, 10, 15, 10, 0)
    options = BenchmarkOptions(
        symbol="000001.SZ",
        start=end - timedelta(minutes=30),
        end=end,
        period="1m",
    )

    results = await benchmark(build_cases(gateway, lambda: akshare, options), repeats=1)

    assert set(results) == {
        "/realtime", "/daily", "/minute", "/full_minute",
        "/adj_factor", "/financial", "/depth5",
    }
    assert all(set(sources) == {"ELTDX", "AkShare"} for sources in results.values())
    assert all(result["record_counts"] == [1] for sources in results.values() for result in sources.values())
    assert all(result["successes"] == 1 for sources in results.values() for result in sources.values())
    assert "codes.latest_stock_list" in gateway.calls
    assert "helpers.full_quotes" in gateway.calls
    assert "corporate.adjustment_factors" in gateway.calls
    assert "f10.finance_report" in gateway.calls
    assert "quotes.get_depth" in gateway.calls
    assert [method for method, _ in akshare.calls] == [
        "helpers.full_quotes", "bars.get", "bars.get", "bars.get",
        "corporate.adjustment_factors", "f10.finance_report", "quotes.get_depth",
    ]
    assert akshare.calls[1][1]["period"] == "day"
    assert akshare.calls[2][1]["period"] == "1m"
    assert akshare.calls[3][1]["count"] == 5000
    assert akshare.calls[5][1]["report_type"] == "zcfzb"


@pytest.mark.asyncio
async def test_benchmark_records_failure_and_continues_other_calls() -> None:
    attempts = 0

    async def flaky() -> list[dict]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary source error")
        return [{"ok": True}]

    async def healthy() -> list[dict]:
        return [{"ok": True}]

    results = await benchmark(
        {"/daily": {"ELTDX": flaky, "AkShare": healthy}},
        repeats=2,
    )

    assert attempts == 2
    eltdx_result = results["/daily"]["ELTDX"]
    assert eltdx_result["successes"] == 1
    assert len(eltdx_result["attempts_seconds"]) == 2
    assert eltdx_result["median_seconds"] >= 0
    assert "temporary source error" in eltdx_result["errors"][0]
    assert results["/daily"]["AkShare"]["successes"] == 2
    assert results["/daily"]["AkShare"]["median_seconds"] >= 0
