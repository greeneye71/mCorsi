from __future__ import annotations


def safe_next(value: str | None, fallback: str) -> str:
    """Return ``value`` only when it is a local absolute path, else ``fallback``."""
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return value
    return fallback
