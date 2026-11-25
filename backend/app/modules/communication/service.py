"""Record external delivery results independently from internal message state."""
from collections.abc import Iterable

from .contracts import MessengerPlatform


def record_messenger_delivery(
    metadata: dict,
    platform: MessengerPlatform | str,
    delivered: Iterable[dict] = (),
    errors: Iterable[dict] = (),
    status: str | None = None,
) -> None:
    """Сохранить результат внешней отправки отдельно."""
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else str(platform)
    delivered_items = [dict(item) for item in delivered]
    error_items = [dict(item) for item in errors]

    if status is None:
        status = (
            "delivered" if delivered_items and not error_items
            else "partial" if delivered_items
            else "failed" if error_items
            else "not_connected"
        )

    # Внешний сбой не меняет статус сообщения в базе UknowApp.
    channels = metadata.setdefault("messenger_deliveries", {})
    channels[platform_value] = {
        "status": status,
        "delivered": delivered_items,
        "errors": error_items,
    }
