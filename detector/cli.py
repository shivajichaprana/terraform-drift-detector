"""
CLI entry point for the Terraform Drift Detector.

Provides two subcommands:
  - detect: Run drift detection against configured Terraform directories
  - report: Generate a report from previously saved detection results
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .drift_checker import DriftChecker
from .models import DetectionRun

logger = logging.getLogger("detector")


def setup_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level.

    Args:
        verbosity: 0=WARNING, 1=INFO, 2+=DEBUG
    """
    levels = {0: logging.WARNING, 1: logging.INFO}
    level = levels.get(verbosity, logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with detect and report subcommands."""
    parser = argparse.ArgumentParser(
        prog="drift-detector",
        description="Terraform Drift Detector — find infrastructure drift before it finds you.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s detect --config config.yaml
  %(prog)s detect --config config.yaml --output-format json --output-file results.json
  %(prog)s report --input results.json --format markdown
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- detect subcommand ---
    detect_parser = subparsers.add_parser(
        "detect",
        help="Run drift detection against Terraform directories",
        description="Scan configured Terraform directories for state drift.",
    )
    detect_parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to YAML configuration file",
    )
    detect_parser.add_argument(
        "-f",
        "--output-format",
        choices=["console", "json", "markdown"],
        default=None,
        help="Output format (overrides config file setting)",
    )
    detect_parser.add_argument(
        "-o",
        "--output-file",
        default=None,
        help="Write results to file instead of stdout",
    )
    detect_parser.add_argument(
        "--notify",
        nargs="*",
        choices=["slack", "email"],
        default=None,
        help="Send notifications via specified channels",
    )
    detect_parser.add_argument(
        "--exit-code",
        action="store_true",
        default=False,
        help="Exit with code 2 if drift is detected (useful for CI)",
    )
    detect_parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for INFO, -vv for DEBUG)",
    )

    # --- report subcommand ---
    report_parser = subparsers.add_parser(
        "report",
        help="Generate a report from saved detection results",
        description="Load previously saved JSON results and render in a different format.",
    )
    report_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to JSON results file from a previous detection run",
    )
    report_parser.add_argument(
        "-f",
        "--format",
        choices=["console", "json", "markdown"],
        default="console",
        help="Output format for the report",
    )
    report_parser.add_argument(
        "-o",
        "--output-file",
        default=None,
        help="Write report to file instead of stdout",
    )
    report_parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity",
    )

    return parser


def cmd_detect(args: argparse.Namespace) -> int:
    """Execute the detect subcommand.

    Loads config, runs drift detection, outputs results, and optionally
    sends notifications.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0=no drift, 1=error, 2=drift detected with --exit-code).
    """
    setup_logging(args.verbose)

    try:
        config = Config.from_file(args.config)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    # Override output format if specified on CLI
    output_format = args.output_format or config.detection.output_format

    # Run detection
    checker = DriftChecker(config)
    detection_run = checker.run()
    detection_run.config_file = args.config

    # Save results if configured
    if config.detection.save_results:
        results_dir = Path(config.detection.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        results_file = results_dir / f"drift-{detection_run.started_at.replace(':', '-')}.json"
        results_file.write_text(detection_run.to_json(), encoding="utf-8")
        logger.info("Results saved to %s", results_file)

    # Output results
    output = _format_output(detection_run, output_format)
    if args.output_file:
        Path(args.output_file).write_text(output, encoding="utf-8")
        logger.info("Output written to %s", args.output_file)
    else:
        print(output)

    # Send notifications if requested
    if args.notify:
        _send_notifications(detection_run, config, args.notify, output_format)

    # Exit code logic
    if args.exit_code and detection_run.has_drift:
        return 2
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Execute the report subcommand.

    Loads saved JSON results and renders them in the requested format.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0=success, 1=error).
    """
    setup_logging(args.verbose)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: %s", args.input)
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in %s: %s", args.input, exc)
        return 1

    # Reconstruct DetectionRun from saved data
    detection_run = _load_detection_run(data)

    output = _format_output(detection_run, args.format)
    if args.output_file:
        Path(args.output_file).write_text(output, encoding="utf-8")
        logger.info("Report written to %s", args.output_file)
    else:
        print(output)

    return 0


def _format_output(run: DetectionRun, fmt: str) -> str:
    """Format detection results for output.

    Args:
        run: The detection run to format.
        fmt: Output format (console, json, markdown).

    Returns:
        Formatted string.
    """
    if fmt == "json":
        return run.to_json()

    if fmt == "markdown":
        return _format_markdown(run)

    return _format_console(run)


def _format_console(run: DetectionRun) -> str:
    """Render detection results as colored console output.

    Args:
        run: The detection run to format.

    Returns:
        Console-formatted string with ANSI colors.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  TERRAFORM DRIFT DETECTION REPORT")
    lines.append("=" * 60)
    lines.append(f"  Started:   {run.started_at}")
    lines.append(f"  Completed: {run.completed_at or 'N/A'}")
    lines.append(f"  Targets:   {run.total_targets}")
    lines.append(f"  With Drift: {run.targets_with_drift}")
    lines.append(f"  Total Drifted Resources: {run.total_drifted_resources}")
    lines.append(f"  Max Severity: {run.max_severity}")
    lines.append("=" * 60)

    for result in run.results:
        status = "\033[31mDRIFT\033[0m" if result.has_drift else "\033[32mOK\033[0m"
        if result.error_message:
            status = "\033[33mERROR\033[0m"

        lines.append(f"\n  [{status}] {result.directory} (workspace: {result.workspace})")

        if result.error_message:
            lines.append(f"    Error: {result.error_message}")

        if result.has_drift:
            lines.append(f"    Drifted resources: {result.total_drifted}")
            for resource in result.drifted_resources:
                severity_color = {
                    "critical": "\033[31m",
                    "high": "\033[91m",
                    "medium": "\033[33m",
                    "low": "\033[36m",
                }.get(str(resource.severity), "")
                reset = "\033[0m"
                lines.append(
                    f"      {severity_color}[{resource.severity}]{reset} "
                    f"{resource.address} → {resource.drift_type}"
                )
                if resource.attribute_changes:
                    attrs = ", ".join(resource.attribute_changes[:5])
                    if len(resource.attribute_changes) > 5:
                        attrs += f" (+{len(resource.attribute_changes) - 5} more)"
                    lines.append(f"        Changed: {attrs}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def _format_markdown(run: DetectionRun) -> str:
    """Render detection results as Markdown.

    Args:
        run: The detection run to format.

    Returns:
        Markdown-formatted string.
    """
    lines = []
    lines.append("# Terraform Drift Detection Report\n")
    lines.append(f"**Started:** {run.started_at}  ")
    lines.append(f"**Completed:** {run.completed_at or 'N/A'}  ")
    lines.append(f"**Targets scanned:** {run.total_targets}  ")
    lines.append(f"**Targets with drift:** {run.targets_with_drift}  ")
    lines.append(f"**Total drifted resources:** {run.total_drifted_resources}  ")
    lines.append(f"**Max severity:** {run.max_severity}\n")

    if not run.has_drift:
        lines.append("> No drift detected across any targets.\n")
        return "\n".join(lines)

    lines.append("## Drift Details\n")

    for result in run.results:
        if not result.has_drift and not result.error_message:
            continue

        emoji = "🔴" if result.has_drift else "⚠️"
        lines.append(f"### {emoji} {result.directory} (`{result.workspace}`)\n")

        if result.error_message:
            lines.append(f"> **Error:** {result.error_message}\n")
            continue

        lines.append("| Resource | Type | Drift | Severity | Changed Attributes |")
        lines.append("|----------|------|-------|----------|--------------------|")

        for resource in result.drifted_resources:
            attrs = ", ".join(resource.attribute_changes[:3]) if resource.attribute_changes else "—"
            if len(resource.attribute_changes) > 3:
                attrs += f" (+{len(resource.attribute_changes) - 3})"
            lines.append(
                f"| `{resource.address}` | {resource.resource_type} "
                f"| {resource.drift_type} | **{resource.severity}** | {attrs} |"
            )

        lines.append("")

    return "\n".join(lines)


def _load_detection_run(data: dict) -> DetectionRun:
    """Reconstruct a DetectionRun from saved JSON data.

    Args:
        data: Dictionary loaded from saved JSON file.

    Returns:
        Reconstructed DetectionRun.
    """
    from .models import DriftedResource, DriftResult, DriftType

    run = DetectionRun(
        started_at=data.get("started_at", ""),
        completed_at=data.get("completed_at"),
        config_file=data.get("config_file"),
    )

    for result_data in data.get("results", []):
        resources = []
        for res_data in result_data.get("drifted_resources", []):
            drift_type_str = res_data.get("drift_type", "change")
            drift_type = DriftType(drift_type_str)
            resources.append(
                DriftedResource(
                    address=res_data["address"],
                    resource_type=res_data["resource_type"],
                    drift_type=drift_type,
                    attribute_changes=res_data.get("attribute_changes", []),
                    before_value=res_data.get("before_value"),
                    after_value=res_data.get("after_value"),
                )
            )

        result = DriftResult(
            directory=result_data["directory"],
            workspace=result_data["workspace"],
            drifted_resources=resources,
            timestamp=result_data.get("timestamp", ""),
            error_message=result_data.get("error_message"),
        )
        run.results.append(result)

    return run


def _send_notifications(
    run: DetectionRun,
    config: Config,
    channels: list,
    output_format: str,
) -> None:
    """Send notifications via configured channels.

    Args:
        run: Detection run results.
        config: Application configuration with notification settings.
        channels: List of notification channels to use.
        output_format: Format for the notification body.
    """
    report_body = _format_markdown(run)

    if "slack" in channels and config.slack:
        try:
            from .notifiers.slack_notifier import SlackNotifier

            notifier = SlackNotifier(config.slack)
            notifier.send(run, report_body)
            logger.info("Slack notification sent")
        except ImportError:
            logger.warning("Slack notifier not available")
        except Exception as exc:
            logger.error("Failed to send Slack notification: %s", exc)

    if "email" in channels and config.email:
        try:
            from .notifiers.email_notifier import EmailNotifier

            notifier = EmailNotifier(config.email)
            notifier.send(run, report_body)
            logger.info("Email notification sent")
        except ImportError:
            logger.warning("Email notifier not available")
        except Exception as exc:
            logger.error("Failed to send email notification: %s", exc)


def main() -> None:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "detect": cmd_detect,
        "report": cmd_report,
    }

    handler = commands.get(args.command)
    if handler:
        exit_code = handler(args)
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
