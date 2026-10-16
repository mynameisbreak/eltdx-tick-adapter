from unittest.mock import Mock

import pandas as pd
import pytest
from datetime import datetime

from app.akshare_client import AkShareClient
from app.models import AdapterError


@pytest.mark.asyncio
async def test_daily_bars_map_akshare_columns() -> None:
    api = Mock()
    api.stock_zh_a_hist.return_value = pd.DataFrame([{
        "日期": "2026-10-15", "开盘": 11, "最高": 12, "最低": 10,
        "收盘": 11.5, "成交量": 100, "成交额": 115000,
    }])
    client = AkShareClient(api)
    rows = await client.call("bars.get", {"code": "sz000001", "period": "day", "count": 30, "adjust": "none"})
    assert rows == [{"code": "sz000001", "date": "2026-10-15", "open": 11.0,
                     "high": 12.0, "low": 10.0, "close": 11.5, "volume": 100.0, "amount": 115000.0}]
    assert api.stock_zh_a_hist.call_args.kwargs["adjust"] == ""


@pytest.mark.asyncio
async def test_realtime_quote_and_name_from_tencent_snapshot() -> None:
    api = Mock()
    api.stock_zh_a_spot_tx.return_value = pd.DataFrame([{
        "code": "sz000001", "name": "平安银行", "zxj": "11.54", "zdf": "1.14",
        "volume": "722626", "turnover": "83471",
    }])
    client = AkShareClient(api)
    listed = await client.call("codes.latest_stock_list", {})
    rows = await client.call("helpers.full_quotes", {"codes": ["sz000001"]})
    assert listed[0]["name"] == "平安银行"
    assert rows[0]["pre_close_price"] == pytest.approx(11.54 / 1.0114)
    assert rows[0]["volume"] == 722626.0


@pytest.mark.asyncio
async def test_minute_and_depth_keep_panel_shapes() -> None:
    api = Mock()
    api.stock_zh_a_hist_min_em.return_value = pd.DataFrame([{
        "时间": "2026-10-15 09:30:00", "开盘": 11, "最高": 12,
        "最低": 10, "收盘": 11.5, "成交量": 100, "成交额": 115000,
    }])
    api.stock_bid_ask_em.return_value = pd.DataFrame([
        {"item": "buy_1", "value": 11.4}, {"item": "buy_1_vol", "value": 10},
        {"item": "sell_1", "value": 11.5}, {"item": "sell_1_vol", "value": 20},
    ])
    client = AkShareClient(api)
    minute = await client.call("bars.get", {"code": "sz000001", "period": "1m", "count": 30})
    depth = await client.call("quotes.get_depth", {"codes": ["sz000001"]})
    assert minute[0]["datetime"] == "2026-10-15 09:30:00"
    assert depth[0]["buy_levels"] == [{"price": 11.4, "volume": 10.0}]
    assert depth[0]["sell_levels"] == [{"price": 11.5, "volume": 20.0}]


@pytest.mark.asyncio
async def test_factor_and_financial_are_mapped_without_nan() -> None:
    api = Mock()
    api.stock_zh_a_daily.return_value = pd.DataFrame([{"date": "2026-10-15", "qfq_factor": "1.02"}])
    api.stock_financial_report_sina.return_value = pd.DataFrame([{"报告日": "20260930", "资产总计": float("nan")}])
    client = AkShareClient(api)
    factor = await client.call("corporate.adjustment_factors", {"code": "sz000001"})
    financial = await client.call("f10.finance_report", {"code": "sz000001", "report_type": "zcfzb"})
    assert factor == [{"date": "2026-10-15", "qfq_scale": 1.02}]
    assert financial[0]["报告日"] == "20260930"
    assert financial[0]["资产总计"] is None


@pytest.mark.asyncio
async def test_unsupported_method_fails_explicitly() -> None:
    with pytest.raises(AdapterError, match="unsupported"):
        await AkShareClient(Mock()).call("unknown", {})


@pytest.mark.asyncio
async def test_daily_bars_use_requested_date_window() -> None:
    api = Mock()
    api.stock_zh_a_hist.return_value = pd.DataFrame()
    client = AkShareClient(api)

    await client.call("bars.get", {
        "code": "sz000001",
        "period": "day",
        "count": 30,
        "start_time": datetime(2026, 9, 1, 9, 30),
        "end_time": datetime(2026, 9, 30, 15, 0),
    })

    assert api.stock_zh_a_hist.call_args.kwargs["start_date"] == "20260901"
    assert api.stock_zh_a_hist.call_args.kwargs["end_date"] == "20260930"


@pytest.mark.asyncio
async def test_minute_bars_use_requested_datetime_window() -> None:
    api = Mock()
    api.stock_zh_a_hist_min_em.return_value = pd.DataFrame()
    client = AkShareClient(api)

    await client.call("bars.get", {
        "code": "sz000001",
        "period": "1m",
        "count": 30,
        "start_time": datetime(2026, 9, 30, 9, 30),
        "end_time": datetime(2026, 9, 30, 10, 0),
    })

    assert api.stock_zh_a_hist_min_em.call_args.kwargs["start_date"] == "2026-09-30 09:30:00"
    assert api.stock_zh_a_hist_min_em.call_args.kwargs["end_date"] == "2026-09-30 10:00:00"
