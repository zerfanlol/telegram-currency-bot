"""Input validation helpers for currency commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

CURRENCY_CODE_RE = re.compile(r"^[A-Za-z]{3}$")
AMOUNT_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


class ValidationError(ValueError):
    """Raised when user input cannot be parsed or is semantically invalid."""


@dataclass(frozen=True, slots=True)
class ConvertQuery:
    """Parsed `/convert` arguments.

    Attributes:
        amount: Positive amount to convert.
        from_code: ISO 4217 source currency (uppercase).
        to_code: ISO 4217 target currency (uppercase).
    """

    amount: Decimal
    from_code: str
    to_code: str


def normalize_currency(code: str) -> str:
    """Normalize and validate a currency code.

    Args:
        code: Raw user input, e.g. ``usd`` or ``EUR``.

    Returns:
        Uppercase three-letter currency code.

    Raises:
        ValidationError: If the code is not a 3-letter alphabetic token.
    """
    cleaned = code.strip().upper()
    if not CURRENCY_CODE_RE.fullmatch(cleaned):
        raise ValidationError(
            f"Неизвестный формат валюты: <code>{_escape(code)}</code>. "
            "Ожидается код ISO 4217 из трёх букв, например USD."
        )
    return cleaned


def parse_amount(raw: str) -> Decimal:
    """Parse a positive decimal amount.

    Accepts both ``.`` and ``,`` as the decimal separator.

    Args:
        raw: Amount as typed by the user.

    Returns:
        Positive `Decimal` value.

    Raises:
        ValidationError: If the value is not a number or is not positive.
    """
    value = raw.strip()
    if not AMOUNT_RE.fullmatch(value):
        raise ValidationError(
            f"Неверная сумма: <code>{_escape(raw)}</code>. Пример: <code>100</code> или <code>12.50</code>."
        )
    normalized = value.replace(",", ".")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValidationError(
            f"Неверная сумма: <code>{_escape(raw)}</code>."
        ) from exc
    if amount <= 0:
        raise ValidationError("Сумма должна быть больше нуля.")
    if amount > Decimal("1000000000000"):
        raise ValidationError("Сумма слишком большая. Укажите значение меньше 1e12.")
    return amount


def parse_convert_args(text: str) -> ConvertQuery:
    """Parse `/convert 100 USD EUR` (command token is optional).

    Args:
        text: Full message text, with or without the `/convert` prefix.

    Returns:
        Structured conversion query.

    Raises:
        ValidationError: If the command shape or values are invalid.
    """
    parts = text.strip().split()
    if parts and parts[0].startswith("/"):
        command = parts[0].split("@", maxsplit=1)[0].lower()
        if command != "/convert":
            raise ValidationError("Используйте формат: <code>/convert 100 USD EUR</code>")
        parts = parts[1:]

    if len(parts) != 3:
        raise ValidationError(
            "Неверный формат команды.\n"
            "Используйте: <code>/convert 100 USD EUR</code>"
        )

    amount = parse_amount(parts[0])
    from_code = normalize_currency(parts[1])
    to_code = normalize_currency(parts[2])
    return ConvertQuery(amount=amount, from_code=from_code, to_code=to_code)


def parse_rates_args(text: str, default: str = "USD") -> str:
    """Parse `/rates USD` and fall back to `default` when the code is omitted.

    Args:
        text: Full message text.
        default: Currency used when the user sends `/rates` without arguments.

    Returns:
        Uppercase currency code.

    Raises:
        ValidationError: If extra tokens are present or the code is invalid.
    """
    parts = text.strip().split()
    if parts and parts[0].startswith("/"):
        parts = parts[1:]
    if not parts:
        return normalize_currency(default)
    if len(parts) != 1:
        raise ValidationError("Используйте формат: <code>/rates USD</code>")
    return normalize_currency(parts[0])


def _escape(value: str) -> str:
    """Escape characters that are special in Telegram HTML mode."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
