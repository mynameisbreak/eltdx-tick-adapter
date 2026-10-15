import httpx
import pytest

from app.providers import FuyaoRestClient, ProviderUnavailable


@pytest.mark.asyncio
async def test_snapshot_sends_key_and_thscodes_and_unwraps_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/a-share/prices/snapshot"
        assert request.url.params["thscodes"] == "000001.SZ"
        assert request.headers["X-api-key"] == "test-key"
        return httpx.Response(
            200,
            json={"code": 0, "data": {"total": 1, "item": [{"thscode": "000001.SZ"}]}},
        )

    client = FuyaoRestClient("https://example.test", "test-key", transport=httpx.MockTransport(handler))

    assert await client.snapshot(["000001.SZ"]) == [{"thscode": "000001.SZ"}]


@pytest.mark.asyncio
async def test_snapshot_raises_on_api_business_error() -> None:
    client = FuyaoRestClient(
        "https://example.test",
        "test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 2001, "message": "unauthorized"})),
    )

    with pytest.raises(ProviderUnavailable, match="2001"):
        await client.snapshot(["000001.SZ"])
@pytest.mark.asyncio
async def test_snapshot_paginates_full_market_using_total() -> None:
    offsets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offsets.append(request.url.params["offset"])
        offset = int(request.url.params["offset"])
        row = {"thscode": f"00000{offset}.SZ"}
        return httpx.Response(200, json={"code": 0, "data": {"total": 2, "item": [row]}})

    client = FuyaoRestClient("https://example.test", "test-key", transport=httpx.MockTransport(handler))

    rows = await client.snapshot()

    assert len(rows) == 2
    assert offsets == ["0", "1"]

@pytest.mark.asyncio
async def test_historical_uses_documented_daily_query_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/a-share/prices/historical"
        assert dict(request.url.params) == {
            "thscode": "000001.SZ",
            "interval": "1d",
            "start": "1000",
            "end": "2000",
            "adjust": "none",
        }
        return httpx.Response(200, json={"code": 0, "data": {"item": [{"date_ms": 1000}]}})

    client = FuyaoRestClient("https://example.test", "test-key", transport=httpx.MockTransport(handler))

    rows = await client.historical("000001.SZ", 1000, 2000)

    assert rows == [{"date_ms": 1000}]

@pytest.mark.asyncio
async def test_stock_sdk_client_sends_json_and_reads_bridge_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.providers import StockSdkClient

    request_payload: dict[str, object] = {}

    class Process:
        returncode = 0

        async def communicate(self, input: bytes) -> tuple[bytes, bytes]:
            request_payload.update(json.loads(input))
            return b'{"ok":true,"result":[{"code":"000001"}]}', b""

    async def create_process(*args: str, **kwargs: object) -> Process:
        assert args[0] == "node"
        return Process()

    monkeypatch.setattr("app.providers.asyncio.create_subprocess_exec", create_process)
    client = StockSdkClient("node", "stock-sdk/bridge.mjs", timeout=3)

    rows = await client.quotes(["sz000001"])

    assert rows == [{"code": "000001"}]
    assert request_payload == {"op": "quotes.cn", "codes": ["sz000001"]}

@pytest.mark.asyncio
async def test_adjustment_events_uses_documented_fuyao_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/a-share/corporate-actions/adjustment-factors"
        assert dict(request.url.params) == {
            "thscode": "600519.SH",
            "from": "2025-01-01",
            "to": "2025-12-31",
        }
        assert request.headers["X-api-key"] == "test-key"
        return httpx.Response(200, json={"code": 0, "data": {"item": [{"ex_date_ms": 1767225600000}]}})

    client = FuyaoRestClient("https://example.test", "test-key", transport=httpx.MockTransport(handler))

    rows = await client.adjustment_events("600519.SH", "2025-01-01", "2025-12-31")

    assert rows == [{"ex_date_ms": 1767225600000}]


@pytest.mark.asyncio
async def test_financial_uses_selected_documented_endpoint_and_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/a-share/financials/balance-sheets"
        assert dict(request.url.params) == {"thscode": "000001.SZ", "period": "annual", "limit": "4"}
        return httpx.Response(200, json={"code": 0, "data": {"item": [{"assets_total": 100}]}})

    client = FuyaoRestClient("https://example.test", "test-key", transport=httpx.MockTransport(handler))

    rows = await client.financial("000001.SZ", "zcfzb")

    assert rows == [{"assets_total": 100}]


@pytest.mark.asyncio
async def test_unknown_financial_report_type_is_not_guessed() -> None:
    client = FuyaoRestClient("https://example.test", "test-key")

    with pytest.raises(ProviderUnavailable, match="unsupported Fuyao financial report type"):
        await client.financial("000001.SZ", "unsupported")
