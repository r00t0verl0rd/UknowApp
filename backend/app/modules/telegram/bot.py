"""Фоновое получение событий Telegram."""

from copy import deepcopy

from aiogram import Dispatcher

from .handlers import router


class ConflictAwareDispatcher(Dispatcher):
    """Остановить polling при конфликте другого экземпляра."""

    @staticmethod
    async def _listen_updates(
        bot,
        polling_timeout=30,
        backoff_config=None,
        allowed_updates=None,
    ):
        # Используем внутренние средства aiogram, меняя только обработку конфликта.
        base_globals = Dispatcher._listen_updates.__func__.__globals__
        Backoff = base_globals["Backoff"]
        default_backoff_config = base_globals["DEFAULT_BACKOFF_CONFIG"]
        GetUpdates = base_globals["GetUpdates"]
        loggers = base_globals["loggers"]

        backoff = Backoff(config=backoff_config or default_backoff_config)
        get_updates = GetUpdates(timeout=polling_timeout, allowed_updates=allowed_updates)
        kwargs = {}
        if bot.session.timeout:
            kwargs["request_timeout"] = int(bot.session.timeout + polling_timeout)

        failed = False
        while True:
            try:
                updates = await bot(get_updates, **kwargs)
            except Exception as exc:
                if type(exc).__name__ == "TelegramConflictError":
                    loggers.dispatcher.error(
                        "Telegram polling conflict for bot id=%d; stopping polling instead of retrying.",
                        bot.id,
                    )
                    raise

                failed = True
                loggers.dispatcher.error(
                    "Failed to fetch updates - %s: %s", type(exc).__name__, exc,
                )
                loggers.dispatcher.warning(
                    "Sleep for %f seconds and try again... (tryings = %d, bot id = %d)",
                    backoff.next_delay,
                    backoff.counter,
                    bot.id,
                )
                await backoff.asleep()
                continue

            if failed:
                loggers.dispatcher.info(
                    "Connection established (tryings = %d, bot id = %d)",
                    backoff.counter,
                    bot.id,
                )
                backoff.reset()
                failed = False

            for update in updates:
                yield update
                get_updates.offset = update.update_id + 1


def create_dispatcher() -> Dispatcher:
    dispatcher = ConflictAwareDispatcher()
    dispatcher.include_router(deepcopy(router))
    return dispatcher


__all__ = ["create_dispatcher"]
