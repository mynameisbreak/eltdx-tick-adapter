from datetime import datetime

import pytest

from app.normalizers import from_tdx_code, normalize_bar, normalize_depth5, normalize_realtime, to_tdx_code


def test_symbol_conversion() -> None:
    assert to_tdx_code("000001.SZ") == "sz000001"
    assert from_tdx_code("sh600000") == "600000.SH"


def test_invalid_symbol() -> None:
    with pytest.raises(ValueError):
        to_tdx_code("000001.US")


def test_realtime_normalization() -> None:
    result = normalize_realtime(
        {
            "code": "sz000001",
            "name": "平安银行",
            "price": 11.23,
            "pre_close": 11.05,
            "pct": 1.63,
            "vol": 100,
        },
        pct_unit="percent",
    )
    assert result is not None
    assert result["symbol"] == "000001.SZ"
    assert result["change_pct"] == pytest.approx(0.0163)


def test_bar_normalization_uses_beijing_wall_clock() -> None:
    result = normalize_bar(
        {"code": "sz000001", "datetime": "2026-09-30T01:35:00+00:00", "close": 11.2},
        "000001.SZ",
    )
    assert result is not None
    assert result["datetime"] == "2026-09-30 09:35:00"

def test_normalize_fuyao_snapshot_fields_and_percent_units() -> None:
    result = normalize_realtime(
        {
            "thscode": "000001.SZ",
            "last_price": 11.23,
            "prev_price": 11.05,
            "price_change": 0.18,
            "price_change_ratio_pct": 1.63,
            "volume": 100,
            "turnover": 1123,
        },
        pct_unit="percent",
    )

    assert result is not None
    assert result["symbol"] == "000001.SZ"
    assert result["prev_close"] == 11.05
    assert result["change_pct"] == pytest.approx(0.0163)
    assert result["change_amount"] == 0.18
    assert result["volume"] == 100
    assert result["amount"] == 1123

def test_normalize_fuyao_daily_bar_fields() -> None:
    from app.normalizers import normalize_daily

    result = normalize_daily(
        {
            "date_ms": 0,
            "open_price": 10,
            "high_price": 12,
            "low_price": 9,
            "close_price": 11,
            "volume": 50,
            "turnover": 550,
        },
        "000001.SZ",
    )

    assert result == {
        "symbol": "000001.SZ",
        "date": "1970-01-01",
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "volume": 50,
        "amount": 550,
    }

def test_normalize_stock_sdk_quote_fields_and_percent_units() -> None:
    result = normalize_realtime(
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "price": 11.41,
            "prevClose": 11.50,
            "change": -0.09,
            "changePercent": -0.78,
            "volume": 1511767,
            "amount": 171970,
        },
        pct_unit="percent",
    )

    assert result is not None
    assert result["last_price"] == 11.41
    assert result["prev_close"] == 11.50
    assert result["change_pct"] == pytest.approx(-0.0078)
    assert result["change_amount"] == -0.09


def test_normalize_stock_sdk_depth_levels() -> None:
    result = normalize_depth5(
        {
            "bid": [{"price": 11.40, "volume": 2536}],
            "ask": [{"price": 11.41, "volume": 586}],
        },
        "000001.SZ",
    )

    assert result == {
        "symbol": "000001.SZ",
        "asks": [[11.41, 586.0]],
        "bids": [[11.40, 2536.0]],
    }

def test_stock_ticker_without_exchange_infers_a_share_market() -> None:
    result = normalize_realtime(
        {
            "code": "000001",
            "name": "平安银行",
            "price": 11.41,
            "prevClose": 11.5,
            "changePercent": -0.78,
        },
        pct_unit="percent",
    )

    assert result is not None
    assert result["symbol"] == "000001.SZ"
