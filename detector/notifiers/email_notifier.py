"""
Email notifier for drift detection alerts.

Sends drift reports via SMTP with support for TLS, HTML formatting,
and configurable recipient lists. Supports both drift-only and
always-send notification modes.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import EmailConfig
    from ..models import DetectionRun

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends drift detection alerts via SMTP email.

    Constructs both plain text (Markdown) and HTML email bodies with
    drift summary, severity indicators, and resource details.

    Args:
        config: Email notification configuration with SMTP settings.
    """

    def __init__(self, config: "EmailConfig") -> None:
        self.smtp_host = config.smtp_host
        self.smtp_port = config.smtp_port
        self.smtp_user = config.smtp_user
        self.smtp_password = config.smtp_password
        self.use_tls = config.use_tls
        self.from_address = config.from_address
        self.to_addresses = config.to_addresses
        self.subject_prefix = config.subject_prefix
        self.notify_on = config.notify_on

    def send(self, run: "DetectionRun", report_body: str = "") -> bool:
        """Send a drift notification email.

        Args:
            run: The detection run results.
            report_body: Pre-formatted Markdown report text.

        Returns:
            True if the email was sent successfully.

        Raises:
            ValueError: If required email configuration is missing.
        """
        self._validate_config()

        if not self._should_notify(run):
            logger.info(
                "Skipping email notification (notify_on=%s, has_drift=%s)",
                self.notify_on,
                run.has_drift,
            )
            return False

        subject = self._build_subject(run)
        html_body = self._build_html(run)
        plain_body = report_body or self._build_plain_text(run)

        return self._send_email(subject, plain_body, html_body)

    def _validate_config(self) -> None:
        """Validate that all required SMTP settings are present."""
        if not self.smtp_host:
            raise ValueError(
                "SMTP host is not configured. "
                "Set 'smtp_host' in config or SMTP_HOST env var."
            )
        if not self.from_address:
            raise ValueError("Email 'from_address' is not configured.")
        if not self.to_addresses:
            raise ValueError("Email 'to_addresses' list is empty.")

    def _should_notify(self, run: "DetectionRun") -> bool:
        """Determine whether a notification should be sent."""
        if self.notify_on == "always":
            return True
        if self.notify_on == "drift" and run.has_drift:
            return True
        if self.notify_on == "error":
            return any(r.error_message for r in run.results)
        return False

    def _build_subject(self, run: "DetectionRun") -> str:
        """Build the email subject line based on drift status."""
        if run.has_drift:
            severity = str(run.max_severity).upper()
            return (
                f"{self.subject_prefix} "
                f"DRIFT DETECTED — {run.total_drifted_resources} resource(s), "
                f"severity: {severity}"
            )
        return f"{self.subject_prefix} No drift detected"

    def _build_plain_text(self, run: "DetectionRun") -> str:
        """Build a plain text email body.

        Args:
            run: The detection run data.

        Returns:
            Plain text formatted report.
        """
        lines = [
            "TERRAFORM DRIFT DETECTION REPORT",
            "=" * 40,
            f"Started:     {run.started_at}",
            f"Completed:   {run.completed_at or 'N/A'}",
            f"Targets:     {run.total_targets}",
            f"With Drift:  {run.targets_with_drift}",
            f"Drifted Res: {run.total_drifted_resources}",
            f"Max Severity:{str(run.max_severity).upper()}",
            "=" * 40,
        ]

        if not run.has_drift:
            lines.append("\nNo drift detected across any targets.")
            return "\n".join(lines)

        for result in run.results:
            if not result.has_drift and not result.error_message:
                continue

            lines.append(f"\n--- {result.directory} ({result.workspace}) ---")

            if result.error_message:
                lines.append(f"  ERROR: {result.error_message}")
                continue

            for resource in result.drifted_resources:
                lines.append(
                    f"  [{str(resource.severity).upper()}] "
                    f"{resource.address} -> {resource.drift_type}"
                )
                if resource.attribute_changes:
                    attrs = ", ".join(resource.attribute_changes[:5])
                    lines.append(f"    Changed: {attrs}")

        return "\n".join(lines)

    def _build_html(self, run: "DetectionRun") -> str:
        """Build an HTML email body with styled tables.

        Args:
            run: The detection run data.

        Returns:
            HTML-formatted report string.
        """
        severity_colors = {
            "critical": "#dc3545",
            "high": "#fd7e14",
            "medium": "#ffc107",
            "low": "#17a2b8",
        }

        status_color = "#dc3545" if run.has_drift else "#28a745"
        status_text = "DRIFT DETECTED" if run.has_drift else "NO DRIFT"

        html_parts = [
            "<!DOCTYPE html>",
            '<html><head><meta charset="utf-8"></head>',
            '<body style="font-family: -apple-system, BlinkMacSystemFont, '
            "sans-serif; max-width: 800px; margin: 0 auto; "
            'padding: 20px; color: #333;">',
            f'<h1 style="border-bottom: 3px solid {status_color}; '
            f'padding-bottom: 10px;">Terraform Drift Report</h1>',
            f'<p style="font-size: 18px; font-weight: bold; '
            f'color: {status_color};">{status_text}</p>',
            '<table style="border-collapse: collapse; width: 100%; '
            'margin: 15px 0;">',
            self._html_summary_row("Started", run.started_at),
            self._html_summary_row("Completed", run.completed_at or "N/A"),
            self._html_summary_row("Targets Scanned", str(run.total_targets)),
            self._html_summary_row(
                "Targets with Drift", str(run.targets_with_drift)
            ),
            self._html_summary_row(
                "Total Drifted Resources",
                str(run.total_drifted_resources),
            ),
            self._html_summary_row(
                "Max Severity",
                f'<span style="color: '
                f'{severity_colors.get(str(run.max_severity), "#666")}">'
                f"{str(run.max_severity).upper()}</span>",
            ),
            "</table>",
        ]

        if not run.has_drift:
            html_parts.append(
                '<p style="color: #28a745; font-weight: bold;">'
                "All targets are in sync with Terraform state.</p>"
            )
        else:
            for result in run.results:
                if not result.has_drift and not result.error_message:
                    continue

                html_parts.append(
                    f"<h2>{result.directory} "
                    f"<small>({result.workspace})</small></h2>"
                )

                if result.error_message:
                    html_parts.append(
                        f'<p style="color: #fd7e14;">Error: '
                        f"{result.error_message}</p>"
                    )
                    continue

                html_parts.append(
                    '<table style="border-collapse: collapse; '
                    'width: 100%; margin: 10px 0;">'
                )
                html_parts.append(
                    '<tr style="background: #f8f9fa;">'
                    '<th style="padding: 8px; border: 1px solid #dee2e6; '
                    'text-align: left;">Resource</th>'
                    '<th style="padding: 8px; border: 1px solid #dee2e6; '
                    'text-align: left;">Type</th>'
                    '<th style="padding: 8px; border: 1px solid #dee2e6; '
                    'text-align: left;">Drift</th>'
                    '<th style="padding: 8px; border: 1px solid #dee2e6; '
                    'text-align: left;">Severity</th>'
                    "</tr>"
                )

                for resource in result.drifted_resources:
                    sev_str = str(resource.severity)
                    sev_color = severity_colors.get(sev_str, "#666")
                    html_parts.append(
                        "<tr>"
                        f'<td style="padding: 8px; border: 1px solid '
                        f'#dee2e6;"><code>{resource.address}</code></td>'
                        f'<td style="padding: 8px; border: 1px solid '
                        f'#dee2e6;">{resource.resource_type}</td>'
                        f'<td style="padding: 8px; border: 1px solid '
                        f'#dee2e6;">{resource.drift_type}</td>'
                        f'<td style="padding: 8px; border: 1px solid '
                        f'#dee2e6; color: {sev_color}; font-weight: bold;">'
                        f"{sev_str.upper()}</td>"
                        "</tr>"
                    )

                html_parts.append("</table>")

        html_parts.extend([
            '<hr style="margin-top: 30px; border: 1px solid #dee2e6;">',
            '<p style="font-size: 12px; color: #6c757d;">'
            "Generated by Terraform Drift Detector</p>",
            "</body></html>",
        ])

        return "\n".join(html_parts)

    def _html_summary_row(self, label: str, value: str) -> str:
        """Build an HTML table row for the summary section."""
        return (
            "<tr>"
            f'<td style="padding: 6px 12px; font-weight: bold; '
            f'border-bottom: 1px solid #eee;">{label}</td>'
            f'<td style="padding: 6px 12px; '
            f'border-bottom: 1px solid #eee;">{value}</td>'
            "</tr>"
        )

    def _send_email(
        self, subject: str, plain_body: str, html_body: str
    ) -> bool:
        """Send the email via SMTP.

        Args:
            subject: Email subject line.
            plain_body: Plain text body.
            html_body: HTML body.

        Returns:
            True if email was sent successfully.
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = ", ".join(self.to_addresses)

        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)

            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            server.sendmail(
                self.from_address,
                self.to_addresses,
                msg.as_string(),
            )
            server.quit()

            logger.info(
                "Email notification sent to %s",
                ", ".join(self.to_addresses),
            )
            return True

        except smtplib.SMTPAuthenticationError as exc:
            logger.error("SMTP authentication failed: %s", exc)
            return False
        except smtplib.SMTPException as exc:
            logger.error("SMTP error: %s", exc)
            return False
        except OSError as exc:
            logger.error("Network error sending email: %s", exc)
            return False
