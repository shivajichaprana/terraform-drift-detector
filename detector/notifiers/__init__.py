"""
Notification senders for drift detection alerts.

Provides a factory function to instantiate notifiers based on
channel name. Supported channels: slack, email.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Union

from .slack_notifier import SlackNotifier
from .email_notifier import EmailNotifier

if TYPE_CHECKING:
    from ..config import Config, SlackConfig, EmailConfig
    from ..models import DetectionRun

logger = logging.getLogger(__name__)

NotifierType = Union[SlackNotifier, EmailNotifier]

_NOTIFIER_MAP = {
    "slack": ("slack", SlackNotifier),
    "email": ("email", EmailNotifier),
}


def get_notifier(channel: str, config: "Config") -> NotifierType:
    """Factory function to create a notifier instance.

    Args:
        channel: Notification channel name (slack, email).
        config: Application configuration with channel-specific settings.

    Returns:
        An instantiated notifier.

    Raises:
        ValueError: If the channel is not recognized or not configured.
    """
    if channel == "slack":
        if not config.slack:
            raise ValueError(
                "Slack notification requested but not configured. "
                "Add a 'notifications.slack' section to your config."
            )
        return SlackNotifier(config.slack)

    if channel == "email":
        if not config.email:
            raise ValueError(
                "Email notification requested but not configured. "
                "Add a 'notifications.email' section to your config."
            )
        return EmailNotifier(config.email)

    valid = ", ".join(sorted(_NOTIFIER_MAP.keys()))
    raise ValueError(
        f"Unknown notification channel '{channel}'. Valid channels: {valid}"
    )


def send_notifications(
    run: "DetectionRun",
    config: "Config",
    channels: list[str],
    report_body: str = "",
) -> dict[str, bool]:
    """Send notifications across multiple channels.

    Args:
        run: The detection run results.
        config: Application configuration.
        channels: List of notification channel names.
        report_body: Pre-formatted report text for notification body.

    Returns:
        Dictionary mapping channel names to send success status.
    """
    results: dict[str, bool] = {}

    for channel in channels:
        try:
            notifier = get_notifier(channel, config)
            success = notifier.send(run, report_body)
            results[channel] = success

            if success:
                logger.info("Notification sent via %s", channel)
            else:
                logger.info("Notification skipped for %s", channel)

        except ValueError as exc:
            logger.warning("Cannot send %s notification: %s", channel, exc)
            results[channel] = False
        except Exception as exc:
            logger.error(
                "Failed to send %s notification: %s", channel, exc
            )
            results[channel] = False

    return results


__all__ = [
    "SlackNotifier",
    "EmailNotifier",
    "get_notifier",
    "send_notifications",
]
