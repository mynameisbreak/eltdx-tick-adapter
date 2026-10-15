from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppSettings:
    gateway_url: str
    gateway_timeout: float
    fuyao_enabled: bool
    fuyao_base_url: str
    fuyao_api_key_env: str
    fuyao_api_key_file: str
    fuyao_timeout: float
    stock_sdk_enabled: bool
    stock_sdk_node: str
    stock_sdk_bridge: str
    stock_sdk_timeout: float
    realtime_sources: tuple[str, ...]
    daily_sources: tuple[str, ...]
    minute_sources: tuple[str, ...]
    depth5_sources: tuple[str, ...]
    benchmark_on_start: bool


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


def load_settings(path: str | None = None) -> AppSettings:
    config_path = Path(path or os.getenv("MARKET_DATA_CONFIG", "config/data_sources.toml"))
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    gateway = raw.get("eltdx", {})
    fuyao = raw.get("fuyao", {})
    stock_sdk = raw.get("stock_sdk", {})
    routing = raw.get("routing", {})
    return AppSettings(
        gateway_url=os.getenv("ELTDX_GATEWAY_URL", gateway.get("url", "http://127.0.0.1:8000")),
        gateway_timeout=float(os.getenv("ELTDX_GATEWAY_TIMEOUT", gateway.get("timeout", 30))),
        fuyao_enabled=_env_bool("FUYAO_ENABLED", bool(fuyao.get("enabled", True))),
        fuyao_base_url=os.getenv("FUYAO_BASE_URL", fuyao.get("base_url", "https://fuyao.aicubes.cn")),
        fuyao_api_key_env=os.getenv("FUYAO_API_KEY_ENV", fuyao.get("api_key_env", "HITHINK_FINANCE_API_KEY")),
        fuyao_api_key_file=os.getenv("FUYAO_API_KEY_FILE", fuyao.get("api_key_file", ".secrets/fuyao_api_key")),
        fuyao_timeout=float(os.getenv("FUYAO_TIMEOUT", fuyao.get("timeout", 30))),
        stock_sdk_enabled=_env_bool("STOCK_SDK_ENABLED", bool(stock_sdk.get("enabled", True))),
        stock_sdk_node=os.getenv("STOCK_SDK_NODE", stock_sdk.get("node", "node")),
        stock_sdk_bridge=os.getenv("STOCK_SDK_BRIDGE", stock_sdk.get("bridge", "stock-sdk/bridge.mjs")),
        stock_sdk_timeout=float(os.getenv("STOCK_SDK_TIMEOUT", stock_sdk.get("timeout", 30))),
        realtime_sources=tuple(routing.get("realtime_sources", ["fuyao", "stock_sdk", "eltdx"])),
        daily_sources=tuple(routing.get("daily_sources", ["fuyao", "stock_sdk", "eltdx"])),
        minute_sources=tuple(routing.get("minute_sources", ["stock_sdk", "eltdx"])),
        depth5_sources=tuple(routing.get("depth5_sources", ["stock_sdk", "eltdx"])),
        benchmark_on_start=_env_bool("DATA_SOURCE_BENCHMARK", bool(routing.get("benchmark_on_start", False))),
    )


def resolve_fuyao_api_key(settings: AppSettings) -> str:
    try:
        file_value = Path(settings.fuyao_api_key_file).expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        file_value = ""
    env_value = os.getenv(settings.fuyao_api_key_env, "").strip()
    return env_value or file_value
