"""Entry point for the Telegram currency bot."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import ConfigError, Settings
from bot.handlers import setup_routers
from bot.services.currency import CurrencyService

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure stdout logging for the process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


async def set_bot_commands(bot: Bot) -> None:
    """Register command hints in Telegram clients.

    Args:
        bot: Authenticated Bot instance.
    """
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Приветствие и популярные пары"),
            BotCommand(command="convert", description="Конвертация: /convert 100 USD EUR"),
            BotCommand(command="rates", description="Топ курсов: /rates USD"),
            BotCommand(command="help", description="Справка"),
        ]
    )


async def main() -> None:
    """Boot settings, HTTP client, scheduler, and long polling."""
    setup_logging()
    try:
        settings = Settings.load()
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    currency = CurrencyService(
        api_url=settings.exchange_api_url,
        cache_ttl=settings.cache_ttl,
        timeout=settings.http_timeout,
    )
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["currency"] = currency
    dp.include_router(setup_routers())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        currency.warmup,
        "interval",
        seconds=settings.cache_ttl,
        id="warmup_rates",
        replace_existing=True,
        kwargs={"bases": ("USD", "EUR", "RUB")},
    )
    scheduler.add_job(
        currency.cleanup_expired,
        "interval",
        seconds=max(settings.cache_ttl, 60),
        id="cleanup_rates",
        replace_existing=True,
    )
    scheduler.start()

    try:
        await currency.warmup()
        await set_bot_commands(bot)
        logger.info("Bot is starting polling")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await currency.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
