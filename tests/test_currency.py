"""Unit tests for validators and the currency service cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from bot.services.currency import (
    ApiUnavailableError,
    CurrencyService,
    RatesSnapshot,
    UnknownCurrencyError,
)
from bot.utils.validators import (
    ValidationError,
    parse_amount,
    parse_convert_args,
    parse_rates_args,
)


def test_parse_convert_args_success() -> None:
    query = parse_convert_args("/convert 100 USD EUR")
    assert query.amount == Decimal("100")
    assert query.from_code == "USD"
    assert query.to_code == "EUR"


def test_parse_convert_args_comma_and_case() -> None:
    query = parse_convert_args("/convert@mybot 12,5 usd rub")
    assert query.amount == Decimal("12.5")
    assert query.from_code == "USD"
    assert query.to_code == "RUB"


def test_parse_convert_args_rejects_bad_shape() -> None:
    with pytest.raises(ValidationError):
        parse_convert_args("/convert 100 USD")
    with pytest.raises(ValidationError):
        parse_convert_args("/convert abc USD EUR")
    with pytest.raises(ValidationError):
        parse_convert_args("/convert 0 USD EUR")
    with pytest.raises(ValidationError):
        parse_convert_args("/convert -5 USD EUR")
    with pytest.raises(ValidationError):
        parse_convert_args("/convert 10 US EUR")


def test_parse_rates_args() -> None:
    assert parse_rates_args("/rates") == "USD"
    assert parse_rates_args("/rates eur") == "EUR"
    with pytest.raises(ValidationError):
        parse_rates_args("/rates USD EUR")


def test_parse_amount_rejects_non_numeric() -> None:
    with pytest.raises(ValidationError):
        parse_amount("10usd")


@pytest.mark.asyncio
async def test_convert_uses_cached_rates() -> None:
    service = CurrencyService(api_url="https://example.test/v4/latest", cache_ttl=600)
    snapshot = RatesSnapshot(
        base="USD",
        date="2026-09-27",
        rates={"USD": Decimal("1"), "EUR": Decimal("0.92"), "RUB": Decimal("90")},
        fetched_at=datetime.now(timezone.utc),
    )
    with patch.object(service, "_fetch_rates", new=AsyncMock(return_value=snapshot)) as fetch:
        first = await service.convert(Decimal("100"), "usd", "eur")
        second = await service.convert(Decimal("50"), "USD", "EUR")
        assert fetch.await_count == 1
        assert first.result == Decimal("92.0000")
        assert second.result == Decimal("46.0000")
        assert first.rate == Decimal("0.92")
    await service.close()


@pytest.mark.asyncio
async def test_expired_cache_refetches() -> None:
    service = CurrencyService(api_url="https://example.test/v4/latest", cache_ttl=600)
    stale = RatesSnapshot(
        base="USD",
        date="2026-09-27",
        rates={"USD": Decimal("1"), "EUR": Decimal("0.90")},
        fetched_at=datetime.now(timezone.utc) - timedelta(minutes=11),
    )
    fresh = RatesSnapshot(
        base="USD",
        date="2026-09-27",
        rates={"USD": Decimal("1"), "EUR": Decimal("0.95")},
        fetched_at=datetime.now(timezone.utc),
    )
    service._cache["USD"] = stale
    with patch.object(service, "_fetch_rates", new=AsyncMock(return_value=fresh)) as fetch:
        result = await service.convert(Decimal("10"), "USD", "EUR")
        assert fetch.await_count == 1
        assert result.rate == Decimal("0.95")
    await service.close()


@pytest.mark.asyncio
async def test_unknown_quote_currency() -> None:
    service = CurrencyService(api_url="https://example.test/v4/latest", cache_ttl=600)
    snapshot = RatesSnapshot(
        base="USD",
        date="2026-09-27",
        rates={"USD": Decimal("1"), "EUR": Decimal("0.92")},
        fetched_at=datetime.now(timezone.utc),
    )
    with patch.object(service, "_fetch_rates", new=AsyncMock(return_value=snapshot)):
        with pytest.raises(UnknownCurrencyError):
            await service.convert(Decimal("1"), "USD", "ZZZ")
    await service.close()


def test_parse_payload_exchangerate_api() -> None:
    service = CurrencyService(api_url="https://example.test/v4/latest")
    payload: dict[str, Any] = {
        "base": "USD",
        "date": "2026-09-27",
        "rates": {"USD": 1, "EUR": 0.92},
    }
    snapshot = service._parse_payload("USD", payload)
    assert snapshot.base == "USD"
    assert snapshot.rates["EUR"] == Decimal("0.92")


def test_parse_payload_rejects_empty() -> None:
    service = CurrencyService(api_url="https://example.test/v4/latest")
    with pytest.raises(ApiUnavailableError):
        service._parse_payload("USD", {"base": "USD", "rates": {}})


@pytest.mark.asyncio
async def test_popular_quotes_skips_base() -> None:
    service = CurrencyService(api_url="https://example.test/v4/latest", cache_ttl=600)
    snapshot = RatesSnapshot(
        base="USD",
        date="2026-09-27",
        rates={
            "USD": Decimal("1"),
            "EUR": Decimal("0.92"),
            "GBP": Decimal("0.78"),
            "JPY": Decimal("150"),
        },
        fetched_at=datetime.now(timezone.utc),
    )
    with patch.object(service, "_fetch_rates", new=AsyncMock(return_value=snapshot)):
        quotes = await service.popular_quotes("USD", limit=10)
    codes = [code for code, _ in quotes]
    assert "USD" not in codes
    assert codes[:3] == ["EUR", "GBP", "JPY"]
    await service.close()
