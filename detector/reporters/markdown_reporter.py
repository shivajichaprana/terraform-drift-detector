"""
Markdown reporter for drift detection results.

Generates Markdown-formatted reports suitable for posting in Slack
messages, GitHub Issues, pull request comments, or wiki pages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import DetectionRun, DriftResult, DriftedResource


_SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
}

_DRIFT_TYPE_EMOJI = {
    "add": "➕",
    "change": "🔄",
    "destroy": "❌",
    "replace": "♻️",
}


class MarkdownReporter:
    """Generates Markdown-formatted drift detection reports.

    Produces clean Markdown with tables, severity indicators, and
    structured sections suitable for various documentation platforms.

    Args:
        include_toc: Include a table of contents for large reports.
        include_remediation: Include remediation hints per resource.
        compact: Use compact table format with fewer columns.
    """

    def __init__(
        self,
        include_toc: bool = False,
        include_remediation: bool = True,
        compact: bool = False,
    ) -> None:
        self.include_toc = include_toc
        self.include_remediation = include_remediation
        self.compact = compact

    def render(self, run: "DetectionRun") -> str:
        """Render a detection run as Markdown.

        Args:
            run: The detection run to format.

        Returns:
            Markdown-formatted string.
        """
        sections: list[str] = []

        sections.append(self._title(run))
        sections.append(self._summary_section(run))

        if not run.has_drift:
            sections.append("> **All clear** — no drift detected across any targets.\n")
            return "\n".join(sections)

        if self.include_toc and len(run.results) > 3:
            sections.append(self._table_of_contents(run))

        for result in run.results:
            if result.has_drift or result.error_message:
                sections.append(self._render_result(result))

        if self.include_remediation:
            sections.append(self._remediation_section())

        return "\n".join(sections)

    def _title(self, run: "DetectionRun") -> str:
        """Render the report title."""
        status = "🚨 Drift Detected" if run.has_drift else "✅ No Drift"
        return f"# Terraform Drift Detection Report — {status}\n"

    def _summary_section(self, run: "DetectionRun") -> str:
        """Render the summary statistics section."""
        lines = [
            "## Summary\n",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| **Started** | {run.started_at} |",
            f"| **Completed** | {run.completed_at or 'N/A'} |",
            f"| **Targets scanned** | {run.total_targets} |",
            f"| **Targets with drift** | {run.targets_with_drift} |",
            f"| **Total drifted resources** | {run.total_drifted_resources} |",
            f"| **Max severity** | {self._severity_badge(run.max_severity)} |",
            "",
        ]
        return "\n".join(lines)

    def _severity_badge(self, severity: "Severity") -> str:
        """Format severity as an emoji badge."""
        emoji = _SEVERITY_EMOJI.get(str(severity), "⚪")
        return f"{emoji} **{str(severity).upper()}**"

    def _table_of_contents(self, run: "DetectionRun") -> str:
        """Generate a table of contents linking to each target section."""
        lines = ["## Table of Contents\n"]
        for result in run.results:
            if result.has_drift or result.error_message:
                anchor = result.directory.replace("/", "").replace(".", "").lower()
                status = "🔴" if result.has_drift else "⚠️"
                lines.append(
                    f"- {status} [{result.directory}](#{anchor}) "
                    f"({result.total_drifted} resources)"
                )
        lines.append("")
        return "\n".join(lines)

    def _render_result(self, result: "DriftResult") -> str:
        """Render a single target's results as a Markdown section."""
        lines: list[str] = []

        emoji = "🔴" if result.has_drift else "⚠️"
        lines.append(
            f"## {emoji} {result.directory} (`{result.workspace}`)\n"
        )

        if result.error_message:
            lines.append(f"> **Error:** {result.error_message}\n")
            return "\n".join(lines)

        # Drift summary line
        summary = result.drift_summary
        summary_parts = []
        for dtype, count in summary.items():
            if count > 0:
                emoji_dt = _DRIFT_TYPE_EMOJI.get(dtype, "")
                summary_parts.append(f"{emoji_dt} {count} {dtype}")
        lines.append(f"**Drift breakdown:** {' | '.join(summary_parts)}\n")

        # Resource table
        if self.compact:
            lines.append("| Resource | Drift | Severity |")
            lines.append("|----------|-------|----------|")
            for resource in result.drifted_resources:
                lines.append(
                    f"| `{resource.address}` "
                    f"| {resource.drift_type} "
                    f"| {self._severity_badge(resource.severity)} |"
                )
        else:
            lines.append(
                "| Resource | Type | Drift | Severity | Changed Attributes |"
            )
            lines.append(
                "|----------|------|-------|----------|--------------------|"
            )
            for resource in result.drifted_resources:
                attrs = self._format_attributes(resource)
                lines.append(
                    f"| `{resource.address}` "
                    f"| `{resource.resource_type}` "
                    f"| {_DRIFT_TYPE_EMOJI.get(str(resource.drift_type), '')} {resource.drift_type} "
                    f"| {self._severity_badge(resource.severity)} "
                    f"| {attrs} |"
                )

        lines.append("")
        return "\n".join(lines)

    def _format_attributes(self, resource: "DriftedResource") -> str:
        """Format attribute changes for table cell display."""
        if not resource.attribute_changes:
            return "—"

        attrs = resource.attribute_changes[:4]
        formatted = ", ".join(f"`{a}`" for a in attrs)
        remaining = len(resource.attribute_changes) - 4
        if remaining > 0:
            formatted += f" (+{remaining} more)"
        return formatted

    def _remediation_section(self) -> str:
        """Render remediation guidance."""
        return "\n".join([
            "## Remediation\n",
            "To resolve detected drift, choose one of the following strategies:\n",
            "1. **Accept infrastructure state** — run `terraform apply -refresh-only` "
            "to update state to match actual infrastructure.",
            "2. **Revert to declared state** — run `terraform apply` to push "
            "declared configuration back to infrastructure.",
            "3. **Update configuration** — modify `.tf` files to match the "
            "desired infrastructure state, then run `terraform plan` to verify.",
            "",
            "> **Tip:** For critical/high severity drift, investigate the root "
            "cause (manual console change, external automation, etc.) before "
            "choosing a remediation strategy.",
            "",
        ])
