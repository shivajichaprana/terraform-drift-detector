"""
Unit tests for the core drift detection engine.

Exercises terraform plan output parsing for all supported drift
scenarios (add, change, destroy, replace, mixed, no drift, errors)
and verifies the DriftChecker correctly classifies and extracts
resource-level drift information.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from detector.config import Config, DetectionConfig, TargetConfig
from detector.drift_checker import (
    DriftChecker,
    EXIT_DRIFT_DETECTED,
    EXIT_ERROR,
    EXIT_NO_CHANGES,
)
from detector.models import DriftType, Severity


# ---------------------------------------------------------------------------
# Plan output parsing
# ---------------------------------------------------------------------------


class TestParsePlanOutput:
    """Tests for DriftChecker._parse_plan_output."""

    def _make_checker(self) -> DriftChecker:
        config = Config(
            targets=[TargetConfig(path="./dummy")],
            detection=DetectionConfig(),
        )
        return DriftChecker(config)

    def test_no_drift_returns_empty(self, plan_output_no_drift: str) -> None:
        checker = self._make_checker()
        result = checker._parse_plan_output(plan_output_no_drift)
        assert result == []

    def test_single_change_detected(self, plan_output_single_change: str) -> None:
        checker = self._make_checker()
        resources = checker._parse_plan_output(plan_output_single_change)

        assert len(resources) == 1
        resource = resources[0]
        assert resource.address == "aws_s3_bucket.example"
        assert resource.resource_type == "aws_s3_bucket"
        assert resource.drift_type == DriftType.CHANGE

    def test_add_operation_detected(self, plan_output_with_add: str) -> None:
        checker = self._make_checker()
        resources = checker._parse_plan_output(plan_output_with_add)

        assert len(resources) == 1
        assert resources[0].drift_type == DriftType.ADD
        assert resources[0].address == "aws_instance.new_worker"

    def test_destroy_operation_detected(self, plan_output_with_destroy: str) -> None:
        checker = self._make_checker()
        resources = checker._parse_plan_output(plan_output_with_destroy)

        assert len(resources) == 1
        assert resources[0].drift_type == DriftType.DESTROY
        # Security group is security-sensitive and destroy escalates to CRITICAL
        assert resources[0].severity == Severity.CRITICAL

    def test_mixed_drift_parses_all_resources(
        self, plan_output_mixed_drift: str
    ) -> None:
        checker = self._make_checker()
        resources = checker._parse_plan_output(plan_output_mixed_drift)

        assert len(resources) == 3

        addresses = {r.address for r in resources}
        assert addresses == {
            "aws_instance.web",
            "aws_s3_bucket.logs",
            "aws_iam_role.old",
        }

        # Count drift types
        types = [r.drift_type for r in resources]
        assert types.count(DriftType.CHANGE) == 1
        assert types.count(DriftType.ADD) == 1
        assert types.count(DriftType.DESTROY) == 1

    def test_summary_fallback_used_when_no_resources_parsed(
        self, plan_output_summary_only: str
    ) -> None:
        checker = self._make_checker()
        resources = checker._parse_plan_output(plan_output_summary_only)

        # 2 add + 3 change + 1 destroy = 6 placeholders
        assert len(resources) == 6

        by_type = {}
        for r in resources:
            by_type[r.drift_type] = by_type.get(r.drift_type, 0) + 1

        assert by_type[DriftType.ADD] == 2
        assert by_type[DriftType.CHANGE] == 3
        assert by_type[DriftType.DESTROY] == 1


# ---------------------------------------------------------------------------
# Drift type mapping
# ---------------------------------------------------------------------------


class TestActionToDriftType:
    """Tests for DriftChecker._action_to_drift_type."""

    @pytest.fixture
    def checker(self) -> DriftChecker:
        config = Config(
            targets=[TargetConfig(path="./dummy")],
            detection=DetectionConfig(),
        )
        return DriftChecker(config)

    @pytest.mark.parametrize(
        "action,expected",
        [
            ("created", DriftType.ADD),
            ("updated", DriftType.CHANGE),
            ("destroyed", DriftType.DESTROY),
            ("replaced", DriftType.REPLACE),
            ("read", DriftType.CHANGE),
            ("UPDATED", DriftType.CHANGE),  # case insensitive
            ("unknown_action", DriftType.CHANGE),  # default
        ],
    )
    def test_action_mapping(
        self, checker: DriftChecker, action: str, expected: DriftType
    ) -> None:
        assert checker._action_to_drift_type(action) == expected


# ---------------------------------------------------------------------------
# Error extraction
# ---------------------------------------------------------------------------


class TestExtractError:
    """Tests for DriftChecker._extract_error."""

    def _make_checker(self) -> DriftChecker:
        config = Config(
            targets=[TargetConfig(path="./dummy")],
            detection=DetectionConfig(),
        )
        return DriftChecker(config)

    def test_error_extracted_from_output(self, plan_output_error: str) -> None:
        checker = self._make_checker()
        message = checker._extract_error(plan_output_error)

        assert "Error:" in message
        assert "Failed to get existing workspaces" in message

    def test_fallback_when_no_error_line(self) -> None:
        checker = self._make_checker()
        message = checker._extract_error("some random output with no error")

        assert "exit code 1" in message.lower()


# ---------------------------------------------------------------------------
# Full detection run
# ---------------------------------------------------------------------------


class TestDriftCheckerRun:
    """Tests for the DriftChecker.run orchestration."""

    def test_empty_config_returns_empty_run(self) -> None:
        config = Config(targets=[], detection=DetectionConfig())
        checker = DriftChecker(config)
        run = checker.run()

        assert run.total_targets == 0
        assert run.has_drift is False
        assert run.completed_at is not None

    def test_disabled_targets_are_skipped(self) -> None:
        config = Config(
            targets=[
                TargetConfig(path="./dummy", enabled=False),
            ],
            detection=DetectionConfig(),
        )
        checker = DriftChecker(config)
        run = checker.run()

        assert run.total_targets == 0

    def test_missing_directory_produces_error_result(self, tmp_path) -> None:
        missing = tmp_path / "definitely-not-here"
        config = Config(
            targets=[TargetConfig(path=str(missing))],
            detection=DetectionConfig(init_before_plan=False),
        )
        checker = DriftChecker(config)
        run = checker.run()

        assert run.total_targets == 1
        result = run.results[0]
        assert result.error_message is not None
        assert "does not exist" in result.error_message
        assert result.plan_exit_code == EXIT_ERROR

    @mock.patch("detector.drift_checker.subprocess.run")
    def test_no_drift_exit_code_zero(
        self,
        mock_run: mock.MagicMock,
        tmp_path,
        plan_output_no_drift: str,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=EXIT_NO_CHANGES,
            stdout=plan_output_no_drift,
            stderr="",
        )

        target_dir = tmp_path / "tf"
        target_dir.mkdir()

        config = Config(
            targets=[TargetConfig(path=str(target_dir))],
            detection=DetectionConfig(init_before_plan=False),
        )
        checker = DriftChecker(config)
        run = checker.run()

        result = run.results[0]
        assert result.plan_exit_code == EXIT_NO_CHANGES
        assert result.has_drift is False
        assert result.error_message is None

    @mock.patch("detector.drift_checker.subprocess.run")
    def test_drift_detected_populates_resources(
        self,
        mock_run: mock.MagicMock,
        tmp_path,
        plan_output_single_change: str,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=EXIT_DRIFT_DETECTED,
            stdout=plan_output_single_change,
            stderr="",
        )

        target_dir = tmp_path / "tf"
        target_dir.mkdir()

        config = Config(
            targets=[TargetConfig(path=str(target_dir))],
            detection=DetectionConfig(init_before_plan=False),
        )
        checker = DriftChecker(config)
        run = checker.run()

        result = run.results[0]
        assert result.plan_exit_code == EXIT_DRIFT_DETECTED
        assert result.has_drift is True
        assert result.total_drifted == 1
        assert result.drifted_resources[0].address == "aws_s3_bucket.example"

    @mock.patch("detector.drift_checker.subprocess.run")
    def test_plan_error_captures_message(
        self,
        mock_run: mock.MagicMock,
        tmp_path,
        plan_output_error: str,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=EXIT_ERROR,
            stdout="",
            stderr=plan_output_error,
        )

        target_dir = tmp_path / "tf"
        target_dir.mkdir()

        config = Config(
            targets=[TargetConfig(path=str(target_dir))],
            detection=DetectionConfig(init_before_plan=False),
        )
        checker = DriftChecker(config)
        run = checker.run()

        result = run.results[0]
        assert result.plan_exit_code == EXIT_ERROR
        assert result.error_message is not None
        assert "Error" in result.error_message

    @mock.patch("detector.drift_checker.subprocess.run")
    def test_plan_timeout_recorded(
        self, mock_run: mock.MagicMock, tmp_path
    ) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="terraform", timeout=30)

        target_dir = tmp_path / "tf"
        target_dir.mkdir()

        config = Config(
            targets=[TargetConfig(path=str(target_dir))],
            detection=DetectionConfig(init_before_plan=False, plan_timeout=30),
        )
        checker = DriftChecker(config)
        run = checker.run()

        result = run.results[0]
        assert "timed out" in (result.error_message or "")
        assert result.plan_exit_code == EXIT_ERROR

    @mock.patch("detector.drift_checker.subprocess.run")
    def test_missing_binary_recorded(
        self, mock_run: mock.MagicMock, tmp_path
    ) -> None:
        mock_run.side_effect = FileNotFoundError("terraform: command not found")

        target_dir = tmp_path / "tf"
        target_dir.mkdir()

        config = Config(
            targets=[TargetConfig(path=str(target_dir))],
            detection=DetectionConfig(init_before_plan=False),
        )
        checker = DriftChecker(config)
        run = checker.run()

        result = run.results[0]
        assert "binary not found" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Severity classification via DriftedResource
# ---------------------------------------------------------------------------


class TestSeverityClassification:
    """Tests that drift severity is assigned correctly."""

    def test_destroy_is_critical(
        self, drifted_resource_destroy
    ) -> None:
        assert drifted_resource_destroy.severity == Severity.CRITICAL

    def test_change_on_non_sensitive_is_medium(
        self, drifted_resource_change
    ) -> None:
        assert drifted_resource_change.severity == Severity.MEDIUM

    def test_sensitive_change_escalates_to_high(self) -> None:
        from detector.models import DriftedResource

        sensitive = DriftedResource(
            address="aws_iam_role.admin",
            resource_type="aws_iam_role",
            drift_type=DriftType.CHANGE,
        )
        assert sensitive.severity == Severity.HIGH

    def test_sensitive_add_also_elevates(self) -> None:
        from detector.models import DriftedResource

        new_sg = DriftedResource(
            address="aws_security_group.new",
            resource_type="aws_security_group",
            drift_type=DriftType.ADD,
        )
        assert new_sg.severity == Severity.HIGH
