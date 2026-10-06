"""What can go wrong in an export. The messages are written for a person and never contain the token."""


class ExporterError(Exception):
    """The export cannot be done (and trying again at once will not help, or it was tried and failed)."""


class ExporterCancelled(Exception):
    """Somebody asked to stop: the requests end, and what was not written yet is lost (nothing was imported)."""


class DiscordHTTPError(ExporterError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Unauthorized(DiscordHTTPError):
    """401: the token is not valid."""


class Forbidden(DiscordHTTPError):
    """403: the bot may not see this channel (or this server)."""


class NotFound(DiscordHTTPError):
    """404: it does not exist (any more), or the bot cannot see it."""
