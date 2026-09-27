"""Inline keyboards for popular currency pairs."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

POPULAR_PAIRS: tuple[tuple[str, str], ...] = (
    ("USD", "EUR"),
    ("USD", "RUB"),
    ("EUR", "RUB"),
    ("EUR", "USD"),
    ("GBP", "USD"),
    ("USD", "GBP"),
    ("USD", "JPY"),
    ("USD", "CNY"),
    ("USD", "KZT"),
    ("EUR", "GBP"),
)

QUICK_AMOUNTS: tuple[str, ...] = ("1", "10", "100", "1000")


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the start/help keyboard with popular FX pairs.

    Returns:
        Inline keyboard with pair buttons and a rates shortcut.
    """
    builder = InlineKeyboardBuilder()
    for source, target in POPULAR_PAIRS:
        builder.button(
            text=f"{source}/{target}",
            callback_data=f"pair:{source}:{target}",
        )
    builder.button(text="📊 Курсы USD", callback_data="rates:USD")
    builder.button(text="📊 Курсы EUR", callback_data="rates:EUR")
    builder.button(text="📊 Курсы RUB", callback_data="rates:RUB")
    builder.adjust(2, 2, 2, 2, 2, 3)
    return builder.as_markup()


def amounts_keyboard(from_code: str, to_code: str) -> InlineKeyboardMarkup:
    """Build amount shortcuts for a selected currency pair.

    Args:
        from_code: Source currency.
        to_code: Target currency.

    Returns:
        Inline keyboard with predefined amounts and a back button.
    """
    builder = InlineKeyboardBuilder()
    for amount in QUICK_AMOUNTS:
        builder.button(
            text=f"{amount} {from_code}",
            callback_data=f"convert:{amount}:{from_code}:{to_code}",
        )
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def after_convert_keyboard(from_code: str, to_code: str) -> InlineKeyboardMarkup:
    """Keyboard shown under a conversion result.

    Args:
        from_code: Source currency.
        to_code: Target currency.

    Returns:
        Markup with reverse pair, more amounts, and main menu.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔄 {to_code} → {from_code}",
                    callback_data=f"pair:{to_code}:{from_code}",
                ),
                InlineKeyboardButton(
                    text="💱 Другая сумма",
                    callback_data=f"pair:{from_code}:{to_code}",
                ),
            ],
            [
                InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main"),
            ],
        ]
    )
