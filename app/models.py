from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BarsRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=100)
    start_time: datetime | None = None
    end_time: datetime | None = None
    period: str = "1m"

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        if value not in {"1m", "5m", "15m", "30m", "60m"}:
            raise ValueError("period must be one of 1m, 5m, 15m, 30m, 60m")
        return value


class AdjFactorRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=100)
    start_time: datetime | None = None
    end_time: datetime | None = None


class FinancialRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=100)
    report_type: str = Field(default="zcfzb", min_length=1, max_length=32)


class DailyRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=100)
    start_time: datetime | None = None
    end_time: datetime | None = None


class RpcRequest(BaseModel):
    id: int | str
    ok: bool
    result: Any = None
    error: dict[str, Any] | None = None


class AdapterError(RuntimeError):
    pass
