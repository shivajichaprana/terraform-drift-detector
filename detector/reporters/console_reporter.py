"""
Console reporter for drift detection results.

Renders drift findings as color-coded terminal output with severity
indicators, resource tables, and summary statistics. Uses ANSI escape
codes for color support in modern terminals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import DetectionRun, DriftResult, DriftedResource, Severity


# ANSI color codes
class _Colors:
    """ANSI escape sequences for terminal coloring."""

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


_SEVERITY_COLORS = {
    "critical": _Colors.RED,
    "high": _Colors.BRIGHT_RED,
    "medium": _Colors.YELLOW,
    "low": _Colors.CYAN,
}

_DRIFT_TYPE_SYMBOLS = {
    "add": "+",
    "change": "~",
    "destroy": "-",
    "replace": "\!",
}


class ConsoleReporter:
    """Generates rich, color-coded console output for drift detection results.

    Supports configurable width, optional color disable for piping to files,
    and verbose mode for detailed attribute change output.

    Args:
        use_color: Enable ANSI color codes. Set False for file output.
        width: Terminal width for separator lines.
        verbose: Show detailed attribute changes for each resource.
    """

    def __init__(
        self,
        use_color: bool = True,
        width: int = 72,
        verbose: bool = False,
    ) -> None:
        self.use_color = use_color
        self.width = width
        self.verbose = verbose

    def render(self, run: "DetectionRun") -> str:
        """Render a complete detection run as console output.

        Args:
            run: The detection run to format.

        Returns:
            Formatted string with ANSI color codes (if enabled).
        """
        lines: list[str] = []

        lines.append(self._header(run))
        lines.append("")

        for result in run.results:
            lines.append(self._render_result(result))

        lines.append(self._footer(run))
        return "\n".join(lines)

    def _color(self, text: str, color: str) -> str:
        """Wrap text in ANSI color codes if color is enabled."""
        if not self.use_color:
            return text
        return f"{color}{text}{_Colors.RESET}"

    def _separator(self, char: str = "=") -> str:
        """Generate a separator line."""
        return char * self.width

    def _header(self, run: "DetectionRun") -> str:
        """Render the report header with summary statistics."""
        sep = self._separator()
        title = self._color("TERRAFORM DRIFT DETECTION REPORT", _Colors.BOLD)

        drift_status = (
            self._color("DRIFT DETECTED", _Colors.RED)
            if run.has_drift
            else self._color("NO DRIFT", _Colors.GREEN)
        )

        lines = [
            sep,
            f"  {title}",
            sep,
            f"  Status:      {drift_status}",
            f"  Started:     {run.started_at}",
            f"  Completed:   {run.completed_at or 'N/A'}",
            f"  Targets:     {run.total_targets}",
            f"  With Drift:  {run.targets_with_drift}",
            f"  Drifted Res: {run.total_drifted_resources}",
            f"  Max Severity:{self._format_severity(run.max_severity)}",
            sep,
        ]
        return "\n".join(lines)

    def _format_severity(self, severity: "Severity") -> str:
        """Format a severity value with appropriate color."""
        severity_str = str(severity).upper()
        color = _SEVERITY_COLORS.get(str(severity), "")
        return f" {self._color(severity_str, color)}"

    def _render_result(self, result: "DriftResult") -> str:
        """Render a single target's drift result."""
        lines: list[str] = []

        # Status badge
        if result.error_message:
            badge = self._color("[ERROR]", _Colors.YELLOW)
        elif result.has_drift:
            badge = self._color("[DRIFT]", _Colors.RED)
        else:
            badge = self._color("[OK]", _Colors.GREEN)

        lines.append(
            f"  {badge} {result.directory} "
            f"{self._color(f'(workspace: {result.workspace})', _Colors.DIM)}"
        )

        if result.error_message:
            lines.append(
                f"    {self._color('Error:', _Colors.YELLOW)} {result.error_message}"
            )
            lines.append("")
            return "\n".join(lines)

        if not result.has_drift:
            lines.append("")
            return "\n".join(lines)

        # Drift summary
        summary = result.drift_summary
        summary_parts = []
        if summary.get("add", 0) > 0:
            summary_parts.append(self._color(f"+{summary['add']} add", _Colors.GREEN))
        if summary.get("change", 0) > 0:
            summary_parts.append(
                self._color(f"~{summary['change']} change", _Colors.YELLOW)
            )
        if summary.get("destroy", 0) > 0:
            summary_parts.append(
                self._color(f"-{summary['destroy']} destroy", _Colors.RED)
            )
        if summary.get("replace", 0) > 0:
            summary_parts.append(
                self._color(f"\!{summary['replace']} replace", _Colors.BRIGHT_RED)
            )

        lines.append(f"    Drifted: {result.total_drifted} ({', '.join(summary_parts)})")
        lines.append("")

        # Resource details
        for resource in result.drifted_resources:
            lines.append(self._render_resource(resource))

        lines.append("")
        return "\n".join(lines)

    def _render_resource(self, resource: "DriftedResource") -> str:
        """Render a single drifted resource entry."""
        symbol = _DRIFT_TYPE_SYMBOLS.get(str(resource.drift_type), "?")
        severity_color = _SEVERITY_COLORS.get(str(resource.severity), "")

        severity_badge = self._color(
            f"[{str(resource.severity).upper()}]", severity_color
        )

        lines = [
            f"      {symbol} {severity_badge} "
            f"{self._color(resource.address, _Colors.BOLD)} "
            f"({resource.resource_type}) -> {resource.drift_type}"
        ]

        if resource.attribute_changes and self.verbose:
            attrs = resource.attribute_changes[:8]
            attr_str = ", ".join(attrs)
            if len(resource.attribute_changes) > 8:
                attr_str += (
                    f" (+{len(resource.attribute_changes) - 8} more)"
                )
            lines.append(
                f"        {self._color('Changed:', _Colors.DIM)} {attr_str}"
            )
        elif resource.attribute_changes:
            count = len(resource.attribute_changes)
            attrs = ", ".join(resource.attribute_changes[:5])
            if count > 5:
                attrs += f" (+{count - 5} more)"
            lines.append(
                f"        {self._color('Changed:', _Colors.DIM)} {attrs}"
            )

        return "\n".join(lines)

    def _footer(self, run: "DetectionRun") -> str:
        """Render the report footer."""
        sep = self._separator()
        if run.has_drift:
            msg = self._color(
                "  ACTION REQUIRED: Review drifted resources and reconcile state.",
                _Colors.BRIGHT_YELLOW,
            )
        else:
            msg = self._color(
                "  All targets are in sync with Terraform state.",
                _Colors.BRIGHT_GREEN,
            )
        return f"\n{msg}\n{sep}"
