from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import AdapterError
from app.providers import ProviderUnavailable


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AsyncMock]:
    gateway = AsyncMock()
    settings = replace(
        main.SETTINGS,
        stock_sdk_enabled=False,
        realtime_sources=tuple(source for source in main.SETTINGS.realtime_sources if source != "stock_sdk"),
    )
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.delenv(settings.fuyao_api_key_env, raising=False)
    monkeypatch.setattr(main, "realtime_source", None)
    monkeypatch.setattr(main, "gateway", gateway)
    with TestClient(main.app) as test_client:
        yield test_client, gateway


def test_health(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
def test_realtime_prefers_fuyao_when_key_is_configured(
    client: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, gateway = client
    fuyao = AsyncMock()
    fuyao.snapshot.return_value = [
        {
            "thscode": "000001.SZ",
            "last_price": 11.23,
            "prev_price": 11.05,
            "price_change_ratio_pct": 1.63,
            "volume": 100,
            "turnover": 1123,
        }
    ]
    gateway.call.return_value = [{"exchange": "sz", "code": "000001", "name": "平安银行"}]
    monkeypatch.setattr(main, "fuyao", fuyao)
    monkeypatch.setattr(main, "realtime_source", None)
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "test-key")

    response = test_client.get("/realtime")

    assert response.status_code == 200
    assert response.json()["data"][0]["name"] == "平安银行"
    assert response.json()["data"][0]["change_pct"] == pytest.approx(0.0163)
    fuyao.snapshot.assert_awaited_once_with()
    assert gateway.call.await_args.args == ("codes.latest_stock_list", {})



def test_realtime_requests_latest_codes_and_normalizes_quote(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.side_effect = [
        [{"exchange": "sz", "code": "000001", "name": "平安银行"}],
        [
            {
                "code": "sz000001",
                "price": 11.23,
                "pre_close_price": 11.05,
                "total_hand": 100,
            }
        ],
    ]

    response = test_client.get("/realtime", params={"symbols": "000001.SZ"})

    assert response.status_code == 200
    quote = response.json()["data"][0]
    assert quote["symbol"] == "000001.SZ"
    assert quote["name"] == "平安银行"
    assert quote["change_pct"] == pytest.approx((11.23 - 11.05) / 11.05)
    assert quote["volume"] == 100.0
    assert gateway.call.await_args_list[0].args == ("codes.latest_stock_list", {})
    assert gateway.call.await_args_list[1].args == (
        "helpers.full_quotes",
        {"codes": ["sz000001"]},
    )


def test_financial_maps_report_type_and_injects_symbol(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = {"rows": [{"rq": "2026-03-31", "T039": 100.0}]}

    response = test_client.post(
        "/financial",
        json={"symbols": ["000001.SZ"], "report_type": "zcfzb"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [{"symbol": "000001.SZ", "rq": "2026-03-31", "T039": 100.0}]
    }
    gateway.call.assert_awaited_once_with(
        "f10.finance_report", {"code": "sz000001", "report_type": "zcfzb"}
    )


def test_daily_maps_day_bars_to_daily_contract(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = [{
        "code": "sz000001",
        "date": "2026-09-30",
        "open": 11.0,
        "high": 11.5,
        "low": 10.9,
        "close": 11.2,
        "volume": 1000,
        "amount": 11200,
    }]

    response = test_client.post("/daily", json={"symbols": ["000001.SZ"]})

    assert response.status_code == 200
    assert response.json()["data"][0] == {
        "symbol": "000001.SZ",
        "date": "2026-09-30",
        "open": 11.0,
        "high": 11.5,
        "low": 10.9,
        "close": 11.2,
        "volume": 1000.0,
        "amount": 11200.0,
    }
    assert gateway.call.await_args.args == (
        "bars.get",
        {"code": "sz000001", "period": "day", "count": 800, "adjust": "none"},
    )


def test_adj_factor_filters_end_time(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = {
        "items": [
            {"date": "2026-09-30", "qfq_scale": 1.25},
            {"date": "2026-10-01", "qfq_scale": 1.30},
        ]
    }

    response = test_client.post(
        "/adj_factor",
        json={"symbols": ["000001.SZ"], "end_time": "2026-09-30T23:59:59+08:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {"symbol": "000001.SZ", "trade_date": "2026-09-30", "ex_factor": 1.25}
    ]


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


def test_minute_filters_rows_outside_requested_window(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = [
        {"code": "sz000001", "datetime": "2026-09-30T09:29:00+08:00", "close": 11.1},
        {"code": "sz000001", "datetime": "2026-09-30T09:30:00+08:00", "close": 11.2},
        {"code": "sz000001", "datetime": "2026-09-30T10:01:00+08:00", "close": 11.3},
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
    assert [row["datetime"] for row in response.json()["data"]] == ["2026-09-30 09:30:00"]


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

def test_depth5_maps_gateway_levels_to_panel_contract(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = {
        "records": [{
            "code": "000001",
            "exchange": "sz",
            "last_price": 11.27,
            "buy_levels": [
                {"price": 11.26, "volume": 10231},
                {"price": 11.25, "volume": 14800},
            ],
            "sell_levels": [
                {"price": 11.27, "volume": 1937},
                {"price": 11.28, "volume": 927},
            ],
        }]
    }

    response = test_client.post("/depth5", json={"symbols": ["000001.SZ"]})

    assert response.status_code == 200
    assert response.json() == {
        "data": [{
            "symbol": "000001.SZ",
            "asks": [[11.27, 1937.0], [11.28, 927.0]],
            "bids": [[11.26, 10231.0], [11.25, 14800.0]],
        }]
    }
    gateway.call.assert_awaited_once_with(
        "quotes.get_depth", {"codes": ["sz000001"]}
    )

def test_realtime_uses_stock_sdk_without_fuyao_key(
    client: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, gateway = client
    settings = replace(main.SETTINGS, stock_sdk_enabled=True, realtime_sources=("stock_sdk", "eltdx"))
    stock_sdk = AsyncMock()
    stock_sdk.quotes.return_value = [{
        "code": "000001",
        "name": "平安银行",
        "price": 11.41,
        "prevClose": 11.50,
        "change": -0.09,
        "changePercent": -0.78,
        "volume": 100,
        "amount": 100,
    }]
    gateway.call.return_value = [{"exchange": "sz", "code": "000001", "name": "平安银行"}]
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "stock_sdk", stock_sdk)

    response = test_client.get("/realtime")

    assert response.status_code == 200
    quote = response.json()["data"][0]
    assert quote["symbol"] == "000001.SZ"
    assert quote["change_pct"] == pytest.approx(-0.0078)
    stock_sdk.quotes.assert_awaited_once_with(["sz000001"])


def test_daily_uses_stock_sdk_when_fuyao_is_not_selected(
    client: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, _ = client
    settings = replace(main.SETTINGS, stock_sdk_enabled=True)
    stock_sdk = AsyncMock()
    stock_sdk.daily.return_value = [{
        "date": "2026-09-30",
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "volume": 100,
        "amount": 1100,
    }]
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "stock_sdk", stock_sdk)

    response = test_client.post("/daily", json={
        "symbols": ["000001.SZ"],
        "start_time": "2026-09-30T00:00:00+08:00",
        "end_time": "2026-09-30T23:59:59+08:00",
    })

    assert response.status_code == 200
    assert response.json()["data"][0]["close"] == 11
    stock_sdk.daily.assert_awaited_once_with("000001.SZ", "20260930", "20260930")


def test_depth5_uses_stock_sdk_quotes(
    client: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, _ = client
    settings = replace(main.SETTINGS, stock_sdk_enabled=True)
    stock_sdk = AsyncMock()
    stock_sdk.quotes.return_value = [{
        "bid": [{"price": 11.4, "volume": 10}],
        "ask": [{"price": 11.41, "volume": 20}],
    }]
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "stock_sdk", stock_sdk)

    response = test_client.post("/depth5", json={"symbols": ["000001.SZ"]})

    assert response.status_code == 200
    assert response.json()["data"][0]["bids"] == [[11.4, 10.0]]
    stock_sdk.quotes.assert_awaited_once_with(["sz000001"])

def test_financial_uses_fuyao_and_preserves_fields(
    client: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, gateway = client
    fuyao = AsyncMock()
    fuyao.financial.return_value = [{"period_end_ms": 1735574400000, "net_profit": 930}]
    monkeypatch.setattr(main, "fuyao", fuyao)
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "test-only")

    response = test_client.post("/financial", json={"symbols": ["600519.SH"], "report_type": "lrb"})

    assert response.status_code == 200
    assert response.json()["data"] == [{"symbol": "600519.SH", "period_end_ms": 1735574400000, "net_profit": 930}]
    fuyao.financial.assert_awaited_once_with("600519.SH", "lrb")
    gateway.call.assert_not_awaited()


def test_financial_unknown_type_falls_back_to_eltdx(client: tuple[TestClient, AsyncMock]) -> None:
    test_client, gateway = client
    gateway.call.return_value = [{"period": "2025", "value": 1}]

    response = test_client.post("/financial", json={"symbols": ["600519.SH"], "report_type": "custom"})

    assert response.status_code == 200
    gateway.call.assert_awaited_once_with("f10.finance_report", {"code": "sh600519", "report_type": "custom"})

def test_financial_provider_and_fallback_errors_return_bad_gateway(
    client: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, gateway = client
    fuyao = AsyncMock()
    fuyao.financial.side_effect = ProviderUnavailable("fuyao unavailable")
    gateway.call.side_effect = AdapterError("eltdx unavailable")
    monkeypatch.setattr(main, "fuyao", fuyao)
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "test-only")

    response = test_client.post("/financial", json={"symbols": ["600519.SH"], "report_type": "lrb"})

    assert response.status_code == 502
    assert response.json()["detail"] == "eltdx unavailable"
