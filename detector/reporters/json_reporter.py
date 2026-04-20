"""
JSON reporter for drift detection results.

Generates structured JSON output with full metadata, suitable for
machine consumption, downstream processing, and integration with
monitoring and alerting systems.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import DetectionRun


class JsonReporter:
    """Generates structured JSON reports from drift detection results.

    Produces a self-contained JSON document with metadata, summary
    statistics, per-target results, and individual resource details.

    Args:
        indent: JSON indentation level. Set to None for compact output.
        include_metadata: Include report generation metadata.
        include_empty_targets: Include targets with no drift in output.
    """

    def __init__(
        self,
        indent: int = 2,
        include_metadata: bool = True,
        include_empty_targets: bool = True,
    ) -> None:
        self.indent = indent
        self.include_metadata = include_metadata
        self.include_empty_targets = include_empty_targets

    def render(self, run: "DetectionRun") -> str:
        """Render a detection run as a JSON string.

        Args:
            run: The detection run to format.

        Returns:
            JSON-formatted string.
        """
        report = self._build_report(run)
        return json.dumps(report, indent=self.indent, default=str)

    def _build_report(self, run: "DetectionRun") -> Dict[str, Any]:
        """Build the complete report dictionary.

        Args:
            run: The detection run data.

        Returns:
            Dictionary ready for JSON serialization.
        """
        report: Dict[str, Any] = {}

        if self.include_metadata:
            report["metadata"] = self._build_metadata(run)

        report["summary"] = self._build_summary(run)
        report["results"] = self._build_results(run)

        return report

    def _build_metadata(self, run: "DetectionRun") -> Dict[str, Any]:
        """Build report metadata section.

        Args:
            run: The detection run data.

        Returns:
            Metadata dictionary with timestamps and config info.
        """
        return {
            "report_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "detection_started_at": run.started_at,
            "detection_completed_at": run.completed_at,
            "config_file": run.config_file,
            "generator": "terraform-drift-detector",
        }

    def _build_summary(self, run: "DetectionRun") -> Dict[str, Any]:
        """Build the summary statistics section.

        Args:
            run: The detection run data.

        Returns:
            Summary dictionary with aggregate statistics.
        """
        drift_by_type: Dict[str, int] = {
            "add": 0,
            "change": 0,
            "destroy": 0,
            "replace": 0,
        }
        drift_by_severity: Dict[str, int] = {
            "low": 0,
            "medium": 0,
            "high": 0,
            "critical": 0,
        }

        for result in run.results:
            for resource in result.drifted_resources:
                drift_type_str = str(resource.drift_type)
                if drift_type_str in drift_by_type:
                    drift_by_type[drift_type_str] += 1
                severity_str = str(resource.severity)
                if severity_str in drift_by_severity:
                    drift_by_severity[severity_str] += 1

        return {
            "has_drift": run.has_drift,
            "total_targets": run.total_targets,
            "targets_with_drift": run.targets_with_drift,
            "total_drifted_resources": run.total_drifted_resources,
            "max_severity": str(run.max_severity),
            "drift_by_type": drift_by_type,
            "drift_by_severity": drift_by_severity,
        }

    def _build_results(self, run: "DetectionRun") -> List[Dict[str, Any]]:
        """Build per-target result details.

        Args:
            run: The detection run data.

        Returns:
            List of result dictionaries.
        """
        results: List[Dict[str, Any]] = []

        for result in run.results:
            if not self.include_empty_targets and not result.has_drift:
                continue

            result_dict: Dict[str, Any] = {
                "directory": result.directory,
                "workspace": result.workspace,
                "timestamp": result.timestamp,
                "has_drift": result.has_drift,
                "total_drifted": result.total_drifted,
                "max_severity": str(result.max_severity),
                "drift_summary": result.drift_summary,
            }

            if result.error_message:
                result_dict["error"] = result.error_message

            result_dict["drifted_resources"] = [
                self._build_resource(r) for r in result.drifted_resources
            ]

            results.append(result_dict)

        return results

    def _build_resource(self, resource: "DriftedResource") -> Dict[str, Any]:
        """Build a single resource entry.

        Args:
            resource: The drifted resource data.

        Returns:
            Resource dictionary.
        """
        entry: Dict[str, Any] = {
            "address": resource.address,
            "resource_type": resource.resource_type,
            "drift_type": str(resource.drift_type),
            "severity": str(resource.severity),
            "attribute_changes": resource.attribute_changes,
        }

        if resource.before_value is not None:
            entry["before_value"] = resource.before_value
        if resource.after_value is not None:
            entry["after_value"] = resource.after_value

        return entry
