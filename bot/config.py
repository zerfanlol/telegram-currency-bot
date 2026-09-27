"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration for the bot.

    Attributes:
        bot_token: Telegram Bot API token from BotFather.
        exchange_api_url: Base URL of the exchange rates API (without currency code).
        cache_ttl: How long fetched rates stay in memory, in seconds.
        http_timeout: HTTP timeout for rate requests, in seconds.
    """

    bot_token: str
    exchange_api_url: str
    cache_ttl: int
    http_timeout: float = 10.0

    @classmethod
    def load(cls) -> Settings:
        """Load settings from the process environment.

        Returns:
            Parsed and validated settings.

        Raises:
            ConfigError: If `BOT_TOKEN` is missing or `CACHE_TTL` is invalid.
        """
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or token == "your_telegram_bot_token_here":
            raise ConfigError(
                "BOT_TOKEN is not set. Copy .env.example to .env and paste a token from @BotFather."
            )

        api_url = os.getenv(
            "EXCHANGE_API_URL",
            "https://api.exchangerate-api.com/v4/latest",
        ).rstrip("/")

        raw_ttl = os.getenv("CACHE_TTL", "600").strip()
        try:
            cache_ttl = int(raw_ttl)
        except ValueError as exc:
            raise ConfigError("CACHE_TTL must be an integer number of seconds.") from exc
        if cache_ttl <= 0:
            raise ConfigError("CACHE_TTL must be a positive integer.")

        return cls(
            bot_token=token,
            exchange_api_url=api_url,
            cache_ttl=cache_ttl,
        )
