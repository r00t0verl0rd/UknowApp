"""Разрешения, публикуемые только после проверки серверной сессии."""

COMMON = frozenset({"dialogs.own", "boards.view"})
ROLE_PERMISSIONS = {
    "admin": COMMON | {"school.manage", "structure.view", "users.manage", "dialogs.observe"},
    "teacher": COMMON | {"structure.view"},
    "student": COMMON,
}


def permits(principal, permission):
    return permission in ROLE_PERMISSIONS.get((principal or {}).get("role"), ())
