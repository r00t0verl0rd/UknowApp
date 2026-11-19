"""Provider-neutral moderation rules for contact data in messages."""

import re

from app.modules.communication.contracts import InboundMessage

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
USERNAME_RE = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{4,}")
TG_LINK_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_]+", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")


def text_contains_contact_data(body: str) -> bool:
    if EMAIL_RE.search(body) or USERNAME_RE.search(body) or TG_LINK_RE.search(body):
        return True
    return any(
        sum(char.isdigit() for char in match) >= 8
        for match in PHONE_RE.findall(body)
    )


def contact_would_be_exposed(message: InboundMessage) -> bool:
    return message.contact_present or text_contains_contact_data(
        message.text or message.caption,
    )
