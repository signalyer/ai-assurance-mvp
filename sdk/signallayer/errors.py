"""Typed error hierarchy for the SignalLayer SDK."""
from __future__ import annotations


class SignalLayerError(Exception):
    """Base exception for all SignalLayer SDK errors."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        """Initialise with a human-readable message and optional HTTP status code.

        Args:
            message: Human-readable description of the error.
            status_code: HTTP status code if this originated from an API response.
        """
        super().__init__(message)
        self.status_code = status_code


class AuthError(SignalLayerError):
    """Raised when the platform rejects the HMAC credentials (HTTP 401)."""

    def __init__(self, message: str = "Authentication failed: invalid API key or signature.") -> None:
        """Initialise AuthError.

        Args:
            message: Human-readable description.
        """
        super().__init__(message, status_code=401)


class PolicyDeniedError(SignalLayerError):
    """Raised when the platform returns a policy DENY decision (HTTP 403)."""

    def __init__(self, message: str = "Request denied by policy engine.") -> None:
        """Initialise PolicyDeniedError.

        Args:
            message: Human-readable description.
        """
        super().__init__(message, status_code=403)


class DecoratorOrderError(SignalLayerError):
    """Raised by order_guard.guard() when the decorator chain is in the wrong order."""

    def __init__(self, message: str) -> None:
        """Initialise DecoratorOrderError.

        Args:
            message: Description of which decorators are out of order.
        """
        super().__init__(message, status_code=0)


class ChainBrokenError(SignalLayerError):
    """Raised when a required decorator is missing from the chain."""

    def __init__(self, message: str) -> None:
        """Initialise ChainBrokenError.

        Args:
            message: Description of which decorator is missing.
        """
        super().__init__(message, status_code=0)
