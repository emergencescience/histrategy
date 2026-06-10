"""SDK-specific exceptions."""


class HistrategyError(Exception):
    """Base exception for all SDK errors."""


class GameNotFoundError(HistrategyError):
    """The requested game was not found (expired or never created)."""


class ConnectionError(HistrategyError):
    """Could not connect to the histrategy server."""


class APIError(HistrategyError):
    """Server returned an error response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class EngineNotAvailableError(HistrategyError):
    """DirectEngine requires histrategy-engine to be installed.

    Install with: pip install histrategy-sdk[engine]
    """


class TurnExecutionError(HistrategyError):
    """Failed to process a game turn."""
