from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import AdapterError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AsyncMock]:
    gateway = AsyncMock()
    monkeypatch.setattr(main, "gateway", gateway)
    with TestClient(main.app) as test_client:
        yield test_client, gateway


def test_health(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_realtime_requests_codes_before_full_market_quotes(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.side_effect = [
        ["sz000001"],
        [
            {
                "code": "sz000001",
                "name": "平安银行",
                "price": 11.23,
                "pre_close": 11.05,
                "pct": 1.63,
            }
        ],
    ]

    response = test_client.get("/realtime", params={"symbols": "000001.SZ"})

    assert response.status_code == 200
    assert response.json()["data"][0]["symbol"] == "000001.SZ"
    assert gateway.call.await_args_list[0].args == ("codes.all_stocks", {})
    assert gateway.call.await_args_list[1].args == (
        "helpers.full_quotes",
        {"codes": ["sz000001"]},
    )


def test_adj_factor_maps_qfq_scale_to_panel_contract(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = {
        "items": [
            {
                "date": "2026-09-30",
                "qfq_scale": 1.25,
                "qfq_offset": 0.0,
            }
        ]
    }

    response = test_client.post(
        "/adj_factor",
        json={"symbols": ["000001.SZ"], "start_time": "2020-01-01T00:00:00+08:00"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {"symbol": "000001.SZ", "trade_date": "2026-09-30", "ex_factor": 1.25}
        ]
    }
    gateway.call.assert_awaited_once_with(
        "corporate.adjustment_factors",
        {"code": "sz000001", "start_date": "2020-01-01"},
    )


def test_minute_maps_request_and_response(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = [
        {
            "code": "sz000001",
            "datetime": "2026-09-30T01:35:00+00:00",
            "open": 11.1,
            "high": 11.3,
            "low": 11.0,
            "close": 11.2,
            "volume": 100,
            "amount": 1120,
        }
    ]

    response = test_client.post(
        "/minute",
        json={
            "symbols": ["000001.SZ"],
            "start_time": "2026-09-30T09:30:00+08:00",
            "end_time": "2026-09-30T10:00:00+08:00",
            "period": "1m",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"][0] == {
        "symbol": "000001.SZ",
        "datetime": "2026-09-30 09:35:00",
        "open": 11.1,
        "high": 11.3,
        "low": 11.0,
        "close": 11.2,
        "volume": 100.0,
        "amount": 1120.0,
    }
    gateway.call.assert_awaited_once()
    assert gateway.call.await_args.args[0] == "bars.get"
    assert gateway.call.await_args.args[1]["code"] == "sz000001"


def test_full_minute_uses_same_contract(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = []

    response = test_client.post(
        "/full_minute",
        json={"symbols": ["600000.SH"], "period": "5m"},
    )

    assert response.status_code == 200
    assert response.json() == {"data": []}


def test_invalid_symbol_returns_bad_request(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, _ = client
    response = test_client.post("/minute", json={"symbols": ["000001.US"]})
    assert response.status_code == 400


def test_invalid_period_returns_unprocessable_entity(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, _ = client
    response = test_client.post("/minute", json={"symbols": ["000001.SZ"], "period": "2m"})
    assert response.status_code == 422


def test_gateway_error_returns_bad_gateway(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.side_effect = AdapterError("upstream unavailable")

    response = test_client.post("/minute", json={"symbols": ["000001.SZ"]})

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream unavailable"
