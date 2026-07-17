from __future__ import annotations


class NotificationGatewayError(Exception):
    """Raised by NotificationGateway implementations on send failure."""

    def __init__(self, channel: str, reason: str) -> None:
        super().__init__(f"Gateway error on {channel}: {reason}")
        self.channel = channel
        self.reason = reason
