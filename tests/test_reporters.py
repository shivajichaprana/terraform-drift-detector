"""
Unit tests for drift detection reporters.

Validates JSON and Markdown reporter output format, content,
configurability (compact mode, metadata inclusion, empty-target
handling), and the get_reporter/render_report factory helpers.
"""

from __future__ import annotations

import json

import pytest

from detector.models import DetectionRun, DriftedResource, DriftResult, DriftType
from detector.reporters import (
    JsonReporter,
    MarkdownReporter,
    get_reporter,
    render_report,
)
from detector.reporters.console_reporter import ConsoleReporter


# ---------------------------------------------------------------------------
# JSON reporter
# ---------------------------------------------------------------------------


class TestJsonReporter:
    """Tests for detector.reporters.json_reporter.JsonReporter."""

    def test_clean_run_produces_valid_json(self, detection_run_clean: DetectionRun) -> None:
        reporter = JsonReporter()
        output = reporter.render(detection_run_clean)

        data = json.loads(output)
        assert data["summary"]["has_drift"] is False
        assert data["summary"]["total_drifted_resources"] == 0
        assert data["summary"]["targets_with_drift"] == 0

    def test_drift_run_includes_all_resources(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        reporter = JsonReporter()
        data = json.loads(reporter.render(detection_run_with_drift))

        assert data["summary"]["has_drift"] is True
        assert data["summary"]["total_drifted_resources"] == 2

        # Find the target with drift
        drifted = [r for r in data["results"] if r["has_drift"]]
        assert len(drifted) == 1
        assert len(drifted[0]["drifted_resources"]) == 2

    def test_metadata_section_present_by_default(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        data = json.loads(JsonReporter().render(detection_run_with_drift))

        assert "metadata" in data
        assert data["metadata"]["generator"] == "terraform-drift-detector"
        assert data["metadata"]["report_version"] == "1.0"

    def test_metadata_can_be_disabled(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        reporter = JsonReporter(include_metadata=False)
        data = json.loads(reporter.render(detection_run_with_drift))

        assert "metadata" not in data

    def test_empty_targets_excluded_when_configured(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        reporter = JsonReporter(include_empty_targets=False)
        data = json.loads(reporter.render(detection_run_with_drift))

        # Only the drifted target should remain
        assert len(data["results"]) == 1
        assert data["results"][0]["has_drift"] is True

    def test_empty_targets_included_by_default(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        data = json.loads(JsonReporter().render(detection_run_with_drift))
        assert len(data["results"]) == 2

    def test_drift_by_type_counts_correct(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        data = json.loads(JsonReporter().render(detection_run_with_drift))
        by_type = data["summary"]["drift_by_type"]

        # One CHANGE + one DESTROY
        assert by_type["change"] == 1
        assert by_type["destroy"] == 1
        assert by_type["add"] == 0
        assert by_type["replace"] == 0

    def test_drift_by_severity_counts_correct(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        data = json.loads(JsonReporter().render(detection_run_with_drift))
        by_sev = data["summary"]["drift_by_severity"]

        # destroy on iam_role -> CRITICAL; change on s3_bucket (non-sensitive) -> MEDIUM
        assert by_sev["critical"] == 1
        assert by_sev["medium"] == 1

    def test_compact_output_without_indent(
        self, detection_run_clean: DetectionRun
    ) -> None:
        reporter = JsonReporter(indent=None)
        output = reporter.render(detection_run_clean)
        # Compact JSON has no newlines or indentation
        assert "\n" not in output


# ---------------------------------------------------------------------------
# Markdown reporter
# ---------------------------------------------------------------------------


class TestMarkdownReporter:
    """Tests for detector.reporters.markdown_reporter.MarkdownReporter."""

    def test_clean_run_shows_all_clear_banner(
        self, detection_run_clean: DetectionRun
    ) -> None:
        output = MarkdownReporter().render(detection_run_clean)
        assert "No Drift" in output
        assert "All clear" in output

    def test_drift_run_includes_summary_table(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        output = MarkdownReporter().render(detection_run_with_drift)

        assert "# Terraform Drift Detection Report" in output
        assert "Drift Detected" in output
        assert "| Metric | Value |" in output
        assert "Total drifted resources" in output

    def test_resources_rendered_in_table(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        output = MarkdownReporter().render(detection_run_with_drift)

        assert "aws_s3_bucket.example" in output
        assert "aws_iam_role.deleted" in output

    def test_compact_mode_reduces_columns(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        compact = MarkdownReporter(compact=True).render(detection_run_with_drift)
        full = MarkdownReporter(compact=False).render(detection_run_with_drift)

        # Full report has the "Changed Attributes" column; compact does not
        assert "Changed Attributes" in full
        assert "Changed Attributes" not in compact

    def test_remediation_section_toggle(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        with_rem = MarkdownReporter(include_remediation=True).render(
            detection_run_with_drift
        )
        without_rem = MarkdownReporter(include_remediation=False).render(
            detection_run_with_drift
        )

        assert "## Remediation" in with_rem
        assert "## Remediation" not in without_rem

    def test_error_target_shows_error_message(
        self, drifted_resource_change: DriftedResource
    ) -> None:
        # Include a drift result alongside the error so the reporter
        # renders per-target sections (it short-circuits on zero drift).
        error_result = DriftResult(
            directory="./infra/broken",
            workspace="default",
            plan_exit_code=1,
            error_message="Backend initialization failed",
        )
        drift_result = DriftResult(
            directory="./infra/prod",
            workspace="default",
            drifted_resources=[drifted_resource_change],
            plan_exit_code=2,
        )
        run = DetectionRun(results=[drift_result, error_result])
        run.mark_completed()

        output = MarkdownReporter().render(run)
        assert "Backend initialization failed" in output
        assert "Error" in output

    def test_severity_badges_use_emoji(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        output = MarkdownReporter().render(detection_run_with_drift)
        # At least one of the severity emojis should be present
        assert any(e in output for e in ["🔴", "🟠", "🟡", "🔵"])


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


class TestReporterFactory:
    """Tests for the get_reporter / render_report helpers."""

    @pytest.mark.parametrize(
        "fmt,expected_type",
        [
            ("console", ConsoleReporter),
            ("json", JsonReporter),
            ("markdown", MarkdownReporter),
        ],
    )
    def test_get_reporter_returns_correct_type(self, fmt, expected_type) -> None:
        assert isinstance(get_reporter(fmt), expected_type)

    def test_get_reporter_unknown_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown report format"):
            get_reporter("xml")

    def test_render_report_json(self, detection_run_clean: DetectionRun) -> None:
        output = render_report(detection_run_clean, fmt="json")
        # must be valid JSON
        data = json.loads(output)
        assert "summary" in data

    def test_render_report_markdown(self, detection_run_clean: DetectionRun) -> None:
        output = render_report(detection_run_clean, fmt="markdown")
        assert output.startswith("# ")

    def test_render_report_forwards_kwargs(
        self, detection_run_with_drift: DetectionRun
    ) -> None:
        output = render_report(
            detection_run_with_drift, fmt="markdown", include_remediation=False
        )
        assert "## Remediation" not in output
