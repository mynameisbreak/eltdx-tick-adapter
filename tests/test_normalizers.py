from datetime import datetime

import pytest

from app.normalizers import from_tdx_code, normalize_bar, normalize_daily, normalize_depth5, normalize_realtime, to_tdx_code


def test_symbol_conversion() -> None:
    assert to_tdx_code("000001.SZ") == "sz000001"
    assert from_tdx_code("sh600000") == "600000.SH"


def test_invalid_symbol() -> None:
    with pytest.raises(ValueError):
        to_tdx_code("000001.US")


def test_realtime_normalization() -> None:
    result = normalize_realtime({"code": "sz000001", "name": "平安银行", "price": 11.23,
                                 "pre_close": 11.05, "pct": 1.63, "vol": 100}, pct_unit="percent")
    assert result is not None
    assert result["symbol"] == "000001.SZ"
    assert result["change_pct"] == pytest.approx(0.0163)


def test_bar_normalization_uses_beijing_wall_clock() -> None:
    result = normalize_bar({"code": "sz000001", "datetime": "2026-09-30T01:35:00+00:00", "close": 11.2}, "000001.SZ")
    assert result is not None
    assert result["datetime"] == "2026-09-30 09:35:00"


def test_akshare_daily_and_depth_keep_contract() -> None:
    daily = normalize_daily({"date": "2026-10-15", "open": 11, "high": 12, "low": 10,
                             "close": 11.5, "volume": 100, "amount": 115000}, "000001.SZ")
    depth = normalize_depth5({"code": "sz000001", "buy_levels": [{"price": 11.4, "volume": 10}],
                              "sell_levels": [{"price": 11.5, "volume": 20}]}, "000001.SZ")
    assert daily is not None and daily["symbol"] == "000001.SZ" and daily["close"] == 11.5
    assert depth is not None and depth["bids"] == [[11.4, 10.0]]
