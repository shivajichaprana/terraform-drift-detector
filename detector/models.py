"""
Data models for drift detection results.

Defines structured representations of drift findings including
per-resource changes, severity classification, and metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class DriftType(Enum):
    """Classification of detected drift operations."""

    ADD = "add"
    CHANGE = "change"
    DESTROY = "destroy"
    REPLACE = "replace"

    def __str__(self) -> str:
        return self.value


class Severity(Enum):
    """Drift severity levels based on impact potential."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __str__(self) -> str:
        return self.value


@dataclass
class DriftedResource:
    """A single resource that has drifted from its declared state."""

    address: str
    resource_type: str
    drift_type: DriftType
    attribute_changes: List[str] = field(default_factory=list)
    before_value: Optional[str] = None
    after_value: Optional[str] = None

    @property
    def severity(self) -> Severity:
        """Classify severity based on drift type and resource characteristics."""
        severity_map = {
            DriftType.DESTROY: Severity.CRITICAL,
            DriftType.REPLACE: Severity.HIGH,
            DriftType.CHANGE: Severity.MEDIUM,
            DriftType.ADD: Severity.LOW,
        }
        # Elevate severity for security-sensitive resource types
        sensitive_types = {
            "aws_iam_role",
            "aws_iam_policy",
            "aws_iam_user",
            "aws_security_group",
            "aws_security_group_rule",
            "aws_kms_key",
            "aws_s3_bucket_policy",
            "aws_vpc",
            "aws_subnet",
            "aws_route_table",
            "google_project_iam_binding",
            "azurerm_role_assignment",
        }
        base_severity = severity_map.get(self.drift_type, Severity.MEDIUM)
        if self.resource_type in sensitive_types and base_severity.value in (
            "low",
            "medium",
        ):
            return Severity.HIGH
        return base_severity

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON output."""
        return {
            "address": self.address,
            "resource_type": self.resource_type,
            "drift_type": str(self.drift_type),
            "severity": str(self.severity),
            "attribute_changes": self.attribute_changes,
            "before_value": self.before_value,
            "after_value": self.after_value,
        }


@dataclass
class DriftResult:
    """Drift detection result for a single Terraform directory/workspace."""

    directory: str
    workspace: str
    drifted_resources: List[DriftedResource] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    plan_exit_code: int = 0
    plan_output: str = ""
    error_message: Optional[str] = None

    @property
    def has_drift(self) -> bool:
        """Check if any drift was detected."""
        return len(self.drifted_resources) > 0

    @property
    def total_drifted(self) -> int:
        """Total number of drifted resources."""
        return len(self.drifted_resources)

    @property
    def max_severity(self) -> Severity:
        """Return the highest severity among all drifted resources."""
        if not self.drifted_resources:
            return Severity.LOW
        severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        max_idx = 0
        for resource in self.drifted_resources:
            idx = severity_order.index(resource.severity)
            if idx > max_idx:
                max_idx = idx
        return severity_order[max_idx]

    @property
    def drift_summary(self) -> dict:
        """Summarize drift by type."""
        summary: dict[str, int] = {
            "add": 0,
            "change": 0,
            "destroy": 0,
            "replace": 0,
        }
        for resource in self.drifted_resources:
            summary[str(resource.drift_type)] += 1
        return summary

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON output."""
        return {
            "directory": self.directory,
            "workspace": self.workspace,
            "timestamp": self.timestamp,
            "has_drift": self.has_drift,
            "total_drifted": self.total_drifted,
            "max_severity": str(self.max_severity),
            "drift_summary": self.drift_summary,
            "drifted_resources": [r.to_dict() for r in self.drifted_resources],
            "error_message": self.error_message,
        }


@dataclass
class DetectionRun:
    """Aggregated results from a full drift detection run across all targets."""

    results: List[DriftResult] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    config_file: Optional[str] = None

    @property
    def total_targets(self) -> int:
        """Number of Terraform directories scanned."""
        return len(self.results)

    @property
    def targets_with_drift(self) -> int:
        """Number of targets where drift was detected."""
        return sum(1 for r in self.results if r.has_drift)

    @property
    def total_drifted_resources(self) -> int:
        """Total drifted resources across all targets."""
        return sum(r.total_drifted for r in self.results)

    @property
    def has_drift(self) -> bool:
        """Check if any target has drift."""
        return any(r.has_drift for r in self.results)

    @property
    def max_severity(self) -> Severity:
        """Highest severity across all results."""
        if not self.results:
            return Severity.LOW
        severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        max_idx = 0
        for result in self.results:
            idx = severity_order.index(result.max_severity)
            if idx > max_idx:
                max_idx = idx
        return severity_order[max_idx]

    def mark_completed(self) -> None:
        """Set the completion timestamp."""
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON output."""
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "config_file": self.config_file,
            "total_targets": self.total_targets,
            "targets_with_drift": self.targets_with_drift,
            "total_drifted_resources": self.total_drifted_resources,
            "has_drift": self.has_drift,
            "max_severity": str(self.max_severity),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
