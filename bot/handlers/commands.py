"""Command handlers: /start, /help, /convert, /rates."""

from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards.inline import after_convert_keyboard, main_menu_keyboard
from bot.services.currency import (
    ApiUnavailableError,
    ConversionResult,
    CurrencyError,
    CurrencyService,
    UnknownCurrencyError,
)
from bot.utils.validators import ValidationError, parse_convert_args, parse_rates_args

logger = logging.getLogger(__name__)
router = Router(name="commands")

START_TEXT = (
    "💱 <b>Currency Bot</b> — конвертер валют с актуальными курсами.\n\n"
    "Я умею:\n"
    "• конвертировать любую сумму: <code>/convert 100 USD EUR</code>\n"
    "• показывать топ курсов: <code>/rates USD</code>\n"
    "• быстро считать популярные пары кнопками ниже\n\n"
    "Курсы кэшируются на 10 минут, источник — "
    "<a href=\"https://www.exchangerate-api.com/\">ExchangeRate-API</a>."
)

HELP_TEXT = (
    "📖 <b>Справка</b>\n\n"
    "<b>/start</b> — приветствие и кнопки популярных пар\n"
    "<b>/convert 100 USD EUR</b> — конвертация суммы\n"
    "<b>/rates USD</b> — топ-10 популярных курсов к валюте\n"
    "<b>/help</b> — эта подсказка\n\n"
    "Коды валют — ISO 4217 из трёх букв: USD, EUR, RUB, GBP, JPY…\n"
    "Сумму можно писать с точкой или запятой: <code>12.5</code> / <code>12,5</code>."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Send a welcome message and the main inline keyboard.

    Args:
        message: Incoming `/start` message.
    """
    await message.answer(
        START_TEXT,
        reply_markup=main_menu_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Send usage instructions.

    Args:
        message: Incoming `/help` message.
    """
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())


@router.message(Command("convert"))
async def cmd_convert(message: Message, currency: CurrencyService) -> None:
    """Convert an amount between two currencies.

    Args:
        message: Incoming `/convert` message.
        currency: Shared currency service from dispatcher workflow data.
    """
    try:
        query = parse_convert_args(message.text or "")
        result = await currency.convert(query.amount, query.from_code, query.to_code)
    except (ValidationError, UnknownCurrencyError) as exc:
        await message.answer(str(exc), reply_markup=main_menu_keyboard())
        return
    except ApiUnavailableError as exc:
        logger.warning("API unavailable during /convert: %s", exc)
        await message.answer(str(exc))
        return
    except CurrencyError:
        logger.exception("Unexpected currency error in /convert")
        await message.answer("Не получилось выполнить конвертацию. Попробуйте позже.")
        return

    await message.answer(
        render_conversion(result),
        reply_markup=after_convert_keyboard(result.from_code, result.to_code),
    )


@router.message(Command("rates"))
async def cmd_rates(message: Message, currency: CurrencyService) -> None:
    """Show popular quotes against the requested base currency.

    Args:
        message: Incoming `/rates` message.
        currency: Shared currency service from dispatcher workflow data.
    """
    try:
        base = parse_rates_args(message.text or "")
        snapshot = await currency.get_rates(base)
        quotes = await currency.popular_quotes(base, limit=10)
    except (ValidationError, UnknownCurrencyError) as exc:
        await message.answer(str(exc), reply_markup=main_menu_keyboard())
        return
    except ApiUnavailableError as exc:
        logger.warning("API unavailable during /rates: %s", exc)
        await message.answer(str(exc))
        return
    except CurrencyError:
        logger.exception("Unexpected currency error in /rates")
        await message.answer("Не получилось загрузить курсы. Попробуйте позже.")
        return

    if not quotes:
        await message.answer("Для этой валюты нет популярных котировок.")
        return

    await message.answer(
        render_rates(snapshot.base, quotes, snapshot.date),
        reply_markup=main_menu_keyboard(),
    )


def format_money(value: Decimal) -> str:
    """Format a decimal for Telegram output.

    Args:
        value: Numeric value.

    Returns:
        Human-readable string without scientific notation.
    """
    abs_value = abs(value)
    if abs_value >= Decimal("1"):
        quantized = value.quantize(Decimal("0.01"))
        return f"{quantized:,.2f}".replace(",", " ")
    if abs_value >= Decimal("0.01"):
        return f"{value.quantize(Decimal('0.0001'))}"
    return f"{value.quantize(Decimal('0.00000001'))}"


def render_conversion(result: ConversionResult) -> str:
    """Build an HTML message for a conversion result.

    Args:
        result: Successful conversion payload.

    Returns:
        HTML-formatted Telegram message.
    """
    return (
        f"💱 <b>{format_money(result.amount)} {result.from_code}</b> = "
        f"<b>{format_money(result.result)} {result.to_code}</b>\n\n"
        f"Курс: 1 {result.from_code} = {format_money(result.rate)} {result.to_code}\n"
        f"Дата курса: {result.date}"
    )


def render_rates(base: str, quotes: list[tuple[str, Decimal]], date: str) -> str:
    """Build an HTML table of popular quotes.

    Args:
        base: Base currency code.
        quotes: Pairs of quote currency and rate.
        date: Rate date from the API.

    Returns:
        HTML-formatted Telegram message.
    """
    lines = [f"📊 <b>Топ курсов к {base}</b>", ""]
    for code, rate in quotes:
        lines.append(f"1 {base} = <code>{format_money(rate)}</code> {code}")
    lines.extend(["", f"Дата курса: {date}"])
    return "\n".join(lines)
