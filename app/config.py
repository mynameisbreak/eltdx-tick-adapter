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
    akshare_enabled: bool
    akshare_timeout: float


def load_settings(path: str | None = None) -> AppSettings:
    config_path = Path(path or os.getenv("MARKET_DATA_CONFIG", "config/data_sources.toml"))
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    eltdx = raw.get("eltdx", {})
    akshare = raw.get("akshare", {})
    return AppSettings(
        gateway_url=os.getenv("ELTDX_GATEWAY_URL", eltdx.get("url", "http://127.0.0.1:8000")),
        gateway_timeout=float(os.getenv("ELTDX_GATEWAY_TIMEOUT", eltdx.get("timeout", 30))),
        akshare_enabled=os.getenv("AKSHARE_ENABLED", str(akshare.get("enabled", True))).lower() in ("true", "1", "yes"),
        akshare_timeout=float(os.getenv("AKSHARE_TIMEOUT", akshare.get("timeout", 30))),
    )
