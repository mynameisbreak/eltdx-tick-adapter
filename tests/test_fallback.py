from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import AdapterError


@pytest.mark.asyncio
async def test_eltdx_is_primary() -> None:
    primary, fallback = AsyncMock(), AsyncMock()
    primary.call.return_value = [{"code": "sz000001"}]
    router = main.FallbackGateway(primary, fallback)
    assert await router.call("bars.get", {"code": "sz000001"}) == [{"code": "sz000001"}]
    fallback.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_akshare_is_used_after_eltdx_failure() -> None:
    primary, fallback = AsyncMock(), AsyncMock()
    primary.call.side_effect = AdapterError("gateway down")
    fallback.call.return_value = [{"date": "2026-10-15", "close": 11.5}]
    router = main.FallbackGateway(primary, fallback)
    assert (await router.call("bars.get", {"code": "sz000001"}))[0]["close"] == 11.5
    fallback.call.assert_awaited_once_with("bars.get", {"code": "sz000001"})


def test_daily_http_contract_on_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    primary, fallback = AsyncMock(), AsyncMock()
    primary.call.side_effect = AdapterError("gateway down")
    fallback.call.return_value = [{"code": "sz000001", "date": "2026-10-15", "open": 11,
                                   "high": 12, "low": 10, "close": 11.5, "volume": 100, "amount": 115000}]
    monkeypatch.setattr(main, "gateway", main.FallbackGateway(primary, fallback))
    with TestClient(main.app) as client:
        response = client.post("/daily", json={"symbols": ["000001.SZ"],
                                               "start_time": "2026-10-15T00:00:00+08:00",
                                               "end_time": "2026-10-15T23:59:59+08:00"})
    assert response.status_code == 200
    assert response.json()["data"] == [{"symbol": "000001.SZ", "date": "2026-10-15",
                                           "open": 11.0, "high": 12.0, "low": 10.0, "close": 11.5,
                                           "volume": 100.0, "amount": 115000.0}]


def test_both_sources_unavailable_returns_bad_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    primary, fallback = AsyncMock(), AsyncMock()
    primary.call.side_effect = AdapterError("gateway down")
    fallback.call.side_effect = AdapterError("AkShare unavailable")
    monkeypatch.setattr(main, "gateway", main.FallbackGateway(primary, fallback))
    with TestClient(main.app) as client:
        response = client.post("/minute", json={"symbols": ["000001.SZ"]})
    assert response.status_code == 502
    assert "AkShare unavailable" in response.json()["detail"]


@pytest.mark.asyncio
async def test_bar_window_is_only_sent_to_akshare() -> None:
    primary, fallback = AsyncMock(), AsyncMock()
    primary.call.side_effect = AdapterError("gateway down")
    fallback.call.return_value = []
    router = main.FallbackGateway(primary, fallback)
    params = {"code": "sz000001", "period": "day", "count": 30,
              "start_time": "2026-09-01T00:00:00+08:00", "end_time": "2026-09-30T23:59:59+08:00"}

    await router.call("bars.get", params)

    primary.call.assert_awaited_once_with("bars.get", {"code": "sz000001", "period": "day", "count": 30})
    fallback.call.assert_awaited_once_with("bars.get", params)
