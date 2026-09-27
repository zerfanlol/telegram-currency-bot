"""Handler routers."""

from aiogram import Router

from bot.handlers.callbacks import router as callbacks_router
from bot.handlers.commands import router as commands_router


def setup_routers() -> Router:
    """Compose command and callback routers.

    Returns:
        Root router with all bot handlers attached.
    """
    root = Router(name="root")
    root.include_router(commands_router)
    root.include_router(callbacks_router)
    return root
