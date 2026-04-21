"""
GitHub Issue notifier for drift detection alerts.

Creates GitHub Issues with structured drift reports when infrastructure
drift is detected. Uses the GitHub REST API via the requests library
or falls back to urllib for environments without requests installed.

Can be invoked as a module for CI integration:
    python -m detector.notifiers.github_notifier \
        --results drift-results.json \
        --repo owner/repo
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import DetectionRun, DriftResult

logger = logging.getLogger(__name__)


class GitHubNotifier:
    """Creates GitHub Issues with drift detection reports.

    Constructs well-formatted Issue bodies with drift summary tables,
    severity indicators, remediation steps, and resource-level details.

    Args:
        token: GitHub personal access token or GITHUB_TOKEN.
        repo: Repository in "owner/repo" format.
        labels: Labels to apply to created Issues.
        assignees: GitHub usernames to assign to Issues.
        api_url: GitHub API base URL (for GitHub Enterprise support).
    """

    SEVERITY_EMOJI = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🔵",
    }

    DRIFT_TYPE_EMOJI = {
        "add": "➕",
        "change": "🔄",
        "destroy": "❌",
        "replace": "♻️",
    }

    def __init__(
        self,
        token: str,
        repo: str,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        api_url: str = "https://api.github.com",
    ) -> None:
        self.token = token
        self.repo = repo
        self.labels = labels or ["drift-detected", "infrastructure"]
        self.assignees = assignees or []
        self.api_url = api_url.rstrip("/")

        if not self.token:
            raise ValueError(
                "GitHub token is required. Set GITHUB_TOKEN environment variable "
                "or pass --token flag."
            )
        if not self.repo or "/" not in self.repo:
            raise ValueError(
                f"Invalid repository format: '{self.repo}'. Expected 'owner/repo'."
            )

    def send(self, run: "DetectionRun", report_body: str = "") -> bool:
        """Create a GitHub Issue for the drift detection results.

        Args:
            run: Detection run results.
            report_body: Optional pre-formatted report body (unused, we generate our own).

        Returns:
            True if the Issue was created successfully.
        """
        if not run.has_drift:
            logger.info("No drift detected, skipping GitHub Issue creation")
            return False

        title = self._build_title(run)
        body = self._build_body(run)

        try:
            issue_url = self._create_issue(title, body)
            logger.info("GitHub Issue created: %s", issue_url)
            return True
        except Exception as exc:
            logger.error("Failed to create GitHub Issue: %s", exc)
            return False

    def _build_title(self, run: "DetectionRun") -> str:
        """Build a descriptive Issue title.

        Args:
            run: Detection run results.

        Returns:
            Issue title string.
        """
        severity = str(run.max_severity).upper()
        resource_count = run.total_drifted_resources
        target_count = run.targets_with_drift
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return (
            f"[{severity}] Infrastructure drift detected: "
            f"{resource_count} resource(s) across {target_count} target(s) "
            f"— {timestamp}"
        )

    def _build_body(self, run: "DetectionRun") -> str:
        """Build a comprehensive Issue body with drift details.

        Args:
            run: Detection run results.

        Returns:
            Markdown-formatted Issue body.
        """
        lines: List[str] = []

        # Header
        lines.append("## 🔍 Terraform Drift Detection Report\n")
        lines.append(
            "Automated drift detection found infrastructure resources "
            "that have diverged from their Terraform-declared state.\n"
        )

        # Summary table
        lines.append("### Summary\n")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| **Detection time** | {run.started_at} |")
        lines.append(f"| **Targets scanned** | {run.total_targets} |")
        lines.append(f"| **Targets with drift** | {run.targets_with_drift} |")
        lines.append(f"| **Total drifted resources** | {run.total_drifted_resources} |")
        lines.append(f"| **Max severity** | {self._severity_badge(str(run.max_severity))} |")
        lines.append("")

        # Per-target details
        lines.append("### Drift Details\n")

        for result in run.results:
            if not result.has_drift:
                continue

            severity_emoji = self.SEVERITY_EMOJI.get(
                str(result.max_severity), "⚪"
            )
            lines.append(
                f"#### {severity_emoji} `{result.directory}` "
                f"(workspace: `{result.workspace}`)\n"
            )

            # Resource table
            lines.append("| Resource | Type | Action | Severity | Changed Attributes |")
            lines.append("|----------|------|--------|----------|--------------------|")

            for resource in result.drifted_resources:
                drift_emoji = self.DRIFT_TYPE_EMOJI.get(
                    str(resource.drift_type), "❓"
                )
                attrs = ", ".join(resource.attribute_changes[:5]) if resource.attribute_changes else "—"
                if len(resource.attribute_changes) > 5:
                    remaining = len(resource.attribute_changes) - 5
                    attrs += f" (+{remaining} more)"

                lines.append(
                    f"| `{resource.address}` "
                    f"| `{resource.resource_type}` "
                    f"| {drift_emoji} {resource.drift_type} "
                    f"| {self._severity_badge(str(resource.severity))} "
                    f"| {attrs} |"
                )

            lines.append("")

            # Drift type summary for this target
            summary = result.drift_summary
            summary_parts = []
            if summary.get("add", 0) > 0:
                summary_parts.append(f"➕ {summary['add']} to add")
            if summary.get("change", 0) > 0:
                summary_parts.append(f"🔄 {summary['change']} to change")
            if summary.get("destroy", 0) > 0:
                summary_parts.append(f"❌ {summary['destroy']} to destroy")
            if summary.get("replace", 0) > 0:
                summary_parts.append(f"♻️ {summary['replace']} to replace")

            if summary_parts:
                lines.append(f"**Summary:** {' | '.join(summary_parts)}\n")

        # Remediation section
        lines.append("### 🛠 Remediation Steps\n")
        lines.append(
            "1. **Investigate** — Determine if the drift was caused by manual changes, "
            "another automation tool, or an external event.\n"
        )
        lines.append(
            "2. **Decide** — Either update Terraform code to match the actual state "
            "(`terraform import` / code changes) or revert the drift "
            "(`terraform apply`).\n"
        )
        lines.append(
            "3. **Apply** — Run `terraform plan` to verify the fix, then "
            "`terraform apply` to reconcile state.\n"
        )
        lines.append(
            "4. **Prevent** — Consider adding Sentinel/OPA policies or "
            "restricting console access to prevent recurrence.\n"
        )

        # Footer
        lines.append("---\n")
        lines.append(
            "*This Issue was created automatically by "
            "[terraform-drift-detector](https://github.com/shivajichaprana/terraform-drift-detector). "
            "Close this Issue once the drift has been resolved.*"
        )

        return "\n".join(lines)

    def _severity_badge(self, severity: str) -> str:
        """Create a severity badge with emoji.

        Args:
            severity: Severity level string.

        Returns:
            Emoji + bold severity text.
        """
        emoji = self.SEVERITY_EMOJI.get(severity, "⚪")
        return f"{emoji} **{severity}**"

    def _create_issue(self, title: str, body: str) -> str:
        """Create a GitHub Issue via the REST API.

        Args:
            title: Issue title.
            body: Issue body (Markdown).

        Returns:
            URL of the created Issue.

        Raises:
            RuntimeError: If the API request fails.
        """
        url = f"{self.api_url}/repos/{self.repo}/issues"

        payload = {
            "title": title,
            "body": body,
            "labels": self.labels,
        }

        if self.assignees:
            payload["assignees"] = self.assignees

        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_data = json.loads(response.read().decode("utf-8"))
                return response_data.get("html_url", "unknown")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8") if exc.fp else "no details"
            raise RuntimeError(
                f"GitHub API returned {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Failed to reach GitHub API: {exc.reason}"
            ) from exc


def _load_run_from_file(results_path: str) -> "DetectionRun":
    """Load a DetectionRun from a saved JSON file.

    Args:
        results_path: Path to JSON results file.

    Returns:
        Reconstructed DetectionRun.
    """
    # Import here to avoid circular imports when used as standalone script
    from ..models import DetectionRun, DriftResult, DriftedResource, DriftType

    with open(results_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    run = DetectionRun(
        started_at=data.get("started_at", ""),
        completed_at=data.get("completed_at"),
        config_file=data.get("config_file"),
    )

    for result_data in data.get("results", []):
        resources = []
        for res_data in result_data.get("drifted_resources", []):
            resources.append(
                DriftedResource(
                    address=res_data["address"],
                    resource_type=res_data["resource_type"],
                    drift_type=DriftType(res_data.get("drift_type", "change")),
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


def main() -> None:
    """CLI entry point for standalone GitHub Issue creation."""
    parser = argparse.ArgumentParser(
        description="Create GitHub Issue from drift detection results",
    )
    parser.add_argument(
        "--results",
        required=True,
        help="Path to JSON results file from drift detection",
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository in owner/repo format",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GH_TOKEN", os.getenv("GITHUB_TOKEN", "")),
        help="GitHub token (default: GH_TOKEN or GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        default=["drift-detected", "infrastructure"],
        help="Labels to apply to the Issue",
    )
    parser.add_argument(
        "--assignees",
        nargs="*",
        default=[],
        help="GitHub usernames to assign",
    )
    parser.add_argument(
        "--api-url",
        default="https://api.github.com",
        help="GitHub API URL (for Enterprise)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    )

    run = _load_run_from_file(args.results)

    if not run.has_drift:
        logger.info("No drift in results, no Issue to create")
        sys.exit(0)

    notifier = GitHubNotifier(
        token=args.token,
        repo=args.repo,
        labels=args.labels,
        assignees=args.assignees,
        api_url=args.api_url,
    )

    success = notifier.send(run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
