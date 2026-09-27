"""Currency rates client with in-memory TTL cache."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import aiohttp

from bot.utils.validators import ValidationError, normalize_currency

logger = logging.getLogger(__name__)

POPULAR_CURRENCIES: tuple[str, ...] = (
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CNY",
    "RUB",
    "CHF",
    "CAD",
    "AUD",
    "INR",
    "BRL",
    "KZT",
)


class CurrencyError(Exception):
    """Base error for the currency service."""


class UnknownCurrencyError(CurrencyError, ValidationError):
    """Raised when the API does not recognize a currency code."""


class ApiUnavailableError(CurrencyError):
    """Raised when the exchange API cannot be reached or returns an error."""


@dataclass(frozen=True, slots=True)
class RatesSnapshot:
    """Cached snapshot of FX rates for a single base currency.

    Attributes:
        base: Base currency code.
        date: Date string reported by the API.
        rates: Mapping of quote currency to rate vs `base`.
        fetched_at: UTC timestamp when this snapshot was stored.
    """

    base: str
    date: str
    rates: dict[str, Decimal]
    fetched_at: datetime

    def is_fresh(self, ttl: int) -> bool:
        """Return True if the snapshot is still within the cache TTL."""
        return datetime.now(timezone.utc) - self.fetched_at < timedelta(seconds=ttl)


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Result of converting an amount between two currencies.

    Attributes:
        amount: Original amount.
        from_code: Source currency.
        to_code: Target currency.
        rate: Units of `to_code` per one `from_code`.
        result: Converted amount.
        date: Rate date from the API.
    """

    amount: Decimal
    from_code: str
    to_code: str
    rate: Decimal
    result: Decimal
    date: str


class CurrencyService:
    """Fetches FX rates asynchronously and caches them in memory.

    Args:
        api_url: Base URL such as ``https://api.exchangerate-api.com/v4/latest``.
        cache_ttl: Cache lifetime in seconds.
        timeout: aiohttp timeout in seconds.
        session: Optional shared `aiohttp.ClientSession`.
    """

    def __init__(
        self,
        api_url: str,
        cache_ttl: int = 600,
        timeout: float = 10.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._cache_ttl = cache_ttl
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._owns_session = session is None
        self._cache: dict[str, RatesSnapshot] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the HTTP session if this service created it."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
            logger.info("Closed aiohttp session")

    async def warmup(self, bases: tuple[str, ...] = ("USD", "EUR", "RUB")) -> None:
        """Prefetch popular bases so the first user request is faster.

        Args:
            bases: Currency codes to refresh in the cache.
        """
        for base in bases:
            try:
                await self.get_rates(base, force_refresh=True)
            except CurrencyError:
                logger.warning("Warmup failed for base=%s", base, exc_info=True)

    async def cleanup_expired(self) -> None:
        """Drop expired cache entries (used by APScheduler)."""
        async with self._lock:
            expired = [
                code
                for code, snapshot in self._cache.items()
                if not snapshot.is_fresh(self._cache_ttl)
            ]
            for code in expired:
                del self._cache[code]
        if expired:
            logger.info("Removed %s expired rate cache entries", len(expired))

    async def get_rates(self, base: str, *, force_refresh: bool = False) -> RatesSnapshot:
        """Return rates for `base`, using the cache when it is still fresh.

        Args:
            base: Base currency code.
            force_refresh: Ignore cache and hit the API.

        Returns:
            Cached or freshly fetched rates snapshot.

        Raises:
            UnknownCurrencyError: If the API does not know this currency.
            ApiUnavailableError: If the API is down or the payload is invalid.
        """
        code = normalize_currency(base)
        if not force_refresh:
            cached = self._cache.get(code)
            if cached is not None and cached.is_fresh(self._cache_ttl):
                logger.debug("Cache hit for %s", code)
                return cached

        async with self._lock:
            if not force_refresh:
                cached = self._cache.get(code)
                if cached is not None and cached.is_fresh(self._cache_ttl):
                    return cached
            snapshot = await self._fetch_rates(code)
            self._cache[code] = snapshot
            logger.info("Cached rates for %s (date=%s)", code, snapshot.date)
            return snapshot

    async def convert(
        self,
        amount: Decimal,
        from_code: str,
        to_code: str,
    ) -> ConversionResult:
        """Convert `amount` from one currency to another.

        Args:
            amount: Positive amount.
            from_code: Source currency.
            to_code: Target currency.

        Returns:
            Conversion result including the applied rate.

        Raises:
            UnknownCurrencyError: If either currency is not in the API response.
            ApiUnavailableError: If rates cannot be loaded.
        """
        source = normalize_currency(from_code)
        target = normalize_currency(to_code)
        snapshot = await self.get_rates(source)
        if target not in snapshot.rates:
            raise UnknownCurrencyError(
                f"Валюта <code>{target}</code> не найдена. Проверьте код ISO 4217."
            )
        rate = snapshot.rates[target]
        result = (amount * rate).quantize(Decimal("0.0001"))
        return ConversionResult(
            amount=amount,
            from_code=source,
            to_code=target,
            rate=rate,
            result=result,
            date=snapshot.date,
        )

    async def popular_quotes(self, base: str, limit: int = 10) -> list[tuple[str, Decimal]]:
        """Return up to `limit` popular quotes against `base`.

        Args:
            base: Base currency shown on the left side of the pair.
            limit: Maximum number of quotes to return.

        Returns:
            List of ``(quote_code, rate)`` pairs, excluding the base itself.
        """
        snapshot = await self.get_rates(base)
        quotes: list[tuple[str, Decimal]] = []
        for code in POPULAR_CURRENCIES:
            if code == snapshot.base:
                continue
            rate = snapshot.rates.get(code)
            if rate is None:
                continue
            quotes.append((code, rate))
            if len(quotes) >= limit:
                break
        return quotes

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def _fetch_rates(self, base: str) -> RatesSnapshot:
        url = f"{self._api_url}/{base}"
        session = await self._session_get()
        logger.debug("GET %s", url)
        try:
            async with session.get(url) as response:
                if response.status in {400, 404, 422}:
                    raise UnknownCurrencyError(
                        f"Валюта <code>{base}</code> не найдена. Проверьте код ISO 4217."
                    )
                if response.status >= 400:
                    raise ApiUnavailableError(
                        "Сервис курсов временно недоступен. Попробуйте через минуту."
                    )
                payload: Any = await response.json(content_type=None)
        except UnknownCurrencyError:
            raise
        except ApiUnavailableError:
            raise
        except aiohttp.ClientError as exc:
            logger.error("HTTP error while fetching %s: %s", url, exc)
            raise ApiUnavailableError(
                "Не удалось связаться с API курсов. Попробуйте позже."
            ) from exc
        except asyncio.TimeoutError as exc:
            logger.error("Timeout while fetching %s", url)
            raise ApiUnavailableError(
                "API курсов не ответил вовремя. Попробуйте позже."
            ) from exc
        except ValueError as exc:
            logger.error("Invalid JSON from %s: %s", url, exc)
            raise ApiUnavailableError(
                "API курсов вернул некорректный ответ."
            ) from exc

        return self._parse_payload(base, payload)

    def _parse_payload(self, requested_base: str, payload: Any) -> RatesSnapshot:
        if not isinstance(payload, dict):
            raise ApiUnavailableError("API курсов вернул некорректный ответ.")

        if payload.get("success") is False:
            error = payload.get("error") or {}
            code = str(error.get("code", "")).lower()
            if "invalid" in code or "not found" in str(error).lower():
                raise UnknownCurrencyError(
                    f"Валюта <code>{requested_base}</code> не найдена. Проверьте код ISO 4217."
                )
            raise ApiUnavailableError("Сервис курсов временно недоступен. Попробуйте через минуту.")

        rates_raw = payload.get("rates")
        base = str(payload.get("base") or requested_base).upper()
        date = str(payload.get("date") or datetime.now(timezone.utc).date().isoformat())
        if not isinstance(rates_raw, dict) or not rates_raw:
            raise ApiUnavailableError("API курсов вернул пустой список курсов.")

        rates: dict[str, Decimal] = {}
        for code, value in rates_raw.items():
            try:
                key = str(code).upper()
                rates[key] = Decimal(str(value))
            except Exception:
                continue
        if not rates:
            raise ApiUnavailableError("API курсов вернул пустой список курсов.")
        rates.setdefault(base, Decimal("1"))
        return RatesSnapshot(
            base=base,
            date=date,
            rates=rates,
            fetched_at=datetime.now(timezone.utc),
        )
