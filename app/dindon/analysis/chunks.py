"""Bound model inputs without discarding the end of a conversation."""


def split_long(text: str, limit: int) -> list[str]:
    """Split at a word boundary when possible; even an unbroken word is retained."""
    if limit < 1:
        raise ValueError("limit must be positive")
    parts = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


def pack_lines(lines: list[str], limit: int) -> list[str]:
    """Pack complete lines into bounded windows, splitting only oversized lines."""
    windows: list[str] = []
    current = ""
    for line in lines:
        for part in split_long(line, limit):
            if current and len(current) + 1 + len(part) > limit:
                windows.append(current)
                current = ""
            current = f"{current}\n{part}" if current else part
    if current:
        windows.append(current)
    return windows
