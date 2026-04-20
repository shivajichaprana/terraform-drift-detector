"""
Slack webhook notifier for drift detection alerts.

Sends formatted drift reports to a Slack channel via incoming webhook.
Supports configurable message formatting, severity-based urgency,
and conditional notification (drift-only or always).
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import SlackConfig
    from ..models import DetectionRun

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends drift detection alerts to Slack via incoming webhook.

    Constructs a Block Kit formatted message with drift summary,
    severity indicators, and per-target resource details.

    Args:
        config: Slack notification configuration with webhook URL and preferences.
    """

    def __init__(self, config: "SlackConfig") -> None:
        self.webhook_url = config.webhook_url
        self.channel = config.channel
        self.username = config.username
        self.icon_emoji = config.icon_emoji
        self.notify_on = config.notify_on

    def send(self, run: "DetectionRun", report_body: str = "") -> bool:
        """Send a drift notification to Slack.

        Args:
            run: The detection run results.
            report_body: Optional pre-formatted report text (Markdown).

        Returns:
            True if the message was sent successfully.

        Raises:
            ValueError: If the webhook URL is not configured.
        """
        if not self.webhook_url:
            raise ValueError(
                "Slack webhook URL is not configured. "
                "Set 'webhook_url' in config or SLACK_WEBHOOK_URL env var."
            )

        # Check notification conditions
        if not self._should_notify(run):
            logger.info(
                "Skipping Slack notification (notify_on=%s, has_drift=%s)",
                self.notify_on,
                run.has_drift,
            )
            return False

        payload = self._build_payload(run, report_body)
        return self._post_webhook(payload)

    def _should_notify(self, run: "DetectionRun") -> bool:
        """Determine whether a notification should be sent.

        Args:
            run: The detection run to evaluate.

        Returns:
            True if notification criteria are met.
        """
        if self.notify_on == "always":
            return True
        if self.notify_on == "drift" and run.has_drift:
            return True
        if self.notify_on == "error":
            return any(r.error_message for r in run.results)
        return False

    def _build_payload(
        self, run: "DetectionRun", report_body: str
    ) -> Dict[str, Any]:
        """Build the Slack webhook payload with Block Kit formatting.

        Args:
            run: The detection run data.
            report_body: Pre-formatted Markdown report text.

        Returns:
            Slack-compatible payload dictionary.
        """
        severity_emoji = {
            "critical": ":red_circle:",
            "high": ":large_orange_circle:",
            "medium": ":large_yellow_circle:",
            "low": ":large_blue_circle:",
        }

        max_sev = str(run.max_severity)
        sev_icon = severity_emoji.get(max_sev, ":white_circle:")

        # Header text
        if run.has_drift:
            header = (
                f":warning: *Terraform Drift Detected* {sev_icon}\n"
                f"*{run.total_drifted_resources}* drifted resource(s) "
                f"across *{run.targets_with_drift}* target(s)"
            )
        else:
            header = ":white_check_mark: *No Terraform Drift Detected*"

        blocks: List[Dict[str, Any]] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header},
            },
            {"type": "divider"},
        ]

        # Summary fields
        fields = [
            f"*Targets Scanned:*\n{run.total_targets}",
            f"*Targets with Drift:*\n{run.targets_with_drift}",
            f"*Total Drifted:*\n{run.total_drifted_resources}",
            f"*Max Severity:*\n{sev_icon} {max_sev.upper()}",
        ]
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f} for f in fields
                ],
            }
        )

        # Per-target details (limit to avoid payload size issues)
        drift_targets = [r for r in run.results if r.has_drift]
        for result in drift_targets[:5]:
            target_text = self._format_target_block(result)
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": target_text},
                }
            )

        if len(drift_targets) > 5:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f":information_source: "
                                f"{len(drift_targets) - 5} additional "
                                f"target(s) with drift not shown."
                            ),
                        }
                    ],
                }
            )

        # Footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f":clock1: Detection ran at {run.started_at} | "
                            f"Config: `{run.config_file or 'N/A'}`"
                        ),
                    }
                ],
            }
        )

        payload: Dict[str, Any] = {"blocks": blocks}
        if self.channel:
            payload["channel"] = self.channel
        if self.username:
            payload["username"] = self.username
        if self.icon_emoji:
            payload["icon_emoji"] = self.icon_emoji

        return payload

    def _format_target_block(self, result: "DriftResult") -> str:
        """Format a single target's drift details for Slack.

        Args:
            result: The drift result for one target.

        Returns:
            Slack mrkdwn formatted string.
        """
        lines = [
            f"*{result.directory}* (`{result.workspace}`)",
            f"Drifted resources: *{result.total_drifted}*",
        ]

        for resource in result.drifted_resources[:10]:
            severity_str = str(resource.severity)
            lines.append(
                f"  • `{resource.address}` — "
                f"{resource.drift_type} ({severity_str})"
            )

        if len(result.drifted_resources) > 10:
            remaining = len(result.drifted_resources) - 10
            lines.append(f"  _...and {remaining} more resource(s)_")

        return "\n".join(lines)

    def _post_webhook(self, payload: Dict[str, Any]) -> bool:
        """Post the payload to the Slack webhook URL.

        Args:
            payload: The Slack message payload.

        Returns:
            True if the webhook responded with 200 OK.
        """
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    logger.info("Slack notification sent successfully")
                    return True
                else:
                    logger.warning(
                        "Slack webhook returned status %d", response.status
                    )
                    return False
        except urllib.error.HTTPError as exc:
            logger.error(
                "Slack webhook HTTP error %d: %s", exc.code, exc.reason
            )
            return False
        except urllib.error.URLError as exc:
            logger.error("Slack webhook connection error: %s", exc.reason)
            return False
