"""Callback query handlers for inline buttons."""

from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.handlers.commands import HELP_TEXT, START_TEXT, render_conversion, render_rates
from bot.keyboards.inline import (
    after_convert_keyboard,
    amounts_keyboard,
    main_menu_keyboard,
)
from bot.services.currency import (
    ApiUnavailableError,
    CurrencyError,
    CurrencyService,
    UnknownCurrencyError,
)
from bot.utils.validators import ValidationError, normalize_currency, parse_amount

logger = logging.getLogger(__name__)
router = Router(name="callbacks")


@router.callback_query(F.data == "menu:main")
async def on_main_menu(callback: CallbackQuery) -> None:
    """Return to the welcome screen.

    Args:
        callback: Inline button callback.
    """
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            START_TEXT,
            reply_markup=main_menu_keyboard(),
            disable_web_page_preview=True,
        )


@router.callback_query(F.data.startswith("pair:"))
async def on_pair(callback: CallbackQuery, currency: CurrencyService) -> None:
    """Show the rate for 1 unit of a popular pair and amount shortcuts.

    Args:
        callback: Inline button callback with ``pair:FROM:TO``.
        currency: Shared currency service.
    """
    if not callback.data:
        await callback.answer("Пустые данные кнопки", show_alert=True)
        return
    try:
        _, from_code, to_code = callback.data.split(":")
        from_code = normalize_currency(from_code)
        to_code = normalize_currency(to_code)
        result = await currency.convert(Decimal("1"), from_code, to_code)
    except (ValidationError, UnknownCurrencyError, ValueError) as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    except ApiUnavailableError as exc:
        logger.warning("API unavailable during pair callback: %s", exc)
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer()
    text = (
        f"{render_conversion(result)}\n\n"
        "Выберите сумму или отправьте "
        f"<code>/convert 250 {from_code} {to_code}</code>"
    )
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=amounts_keyboard(from_code, to_code),
        )


@router.callback_query(F.data.startswith("convert:"))
async def on_convert_amount(callback: CallbackQuery, currency: CurrencyService) -> None:
    """Convert a predefined amount for the selected pair.

    Args:
        callback: Inline button callback with ``convert:AMOUNT:FROM:TO``.
        currency: Shared currency service.
    """
    if not callback.data:
        await callback.answer("Пустые данные кнопки", show_alert=True)
        return
    try:
        _, amount_raw, from_code, to_code = callback.data.split(":")
        amount = parse_amount(amount_raw)
        result = await currency.convert(amount, from_code, to_code)
    except (ValidationError, UnknownCurrencyError, ValueError) as exc:
        await callback.answer("Не удалось выполнить конвертацию", show_alert=True)
        logger.info("Bad convert callback %s: %s", callback.data, exc)
        return
    except ApiUnavailableError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except CurrencyError:
        logger.exception("Unexpected currency error in convert callback")
        await callback.answer("Ошибка конвертации", show_alert=True)
        return

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            render_conversion(result),
            reply_markup=after_convert_keyboard(result.from_code, result.to_code),
        )


@router.callback_query(F.data.startswith("rates:"))
async def on_rates(callback: CallbackQuery, currency: CurrencyService) -> None:
    """Show popular quotes from an inline rates button.

    Args:
        callback: Inline button callback with ``rates:BASE``.
        currency: Shared currency service.
    """
    if not callback.data:
        await callback.answer("Пустые данные кнопки", show_alert=True)
        return
    try:
        _, base = callback.data.split(":")
        snapshot = await currency.get_rates(base)
        quotes = await currency.popular_quotes(base, limit=10)
    except (ValidationError, UnknownCurrencyError, ValueError) as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    except ApiUnavailableError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            render_rates(snapshot.base, quotes, snapshot.date),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data == "help")
async def on_help(callback: CallbackQuery) -> None:
    """Show help from an inline button.

    Args:
        callback: Inline button callback.
    """
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(HELP_TEXT, reply_markup=main_menu_keyboard())
