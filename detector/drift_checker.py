"""
Core drift detection engine.

Runs `terraform plan -detailed-exitcode` against configured directories,
parses plan output for infrastructure drift, and captures resource-level
changes with type classification.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .config import Config, TargetConfig, DetectionConfig
from .models import (
    DetectionRun,
    DriftedResource,
    DriftResult,
    DriftType,
)

logger = logging.getLogger(__name__)

# Terraform plan exit codes
EXIT_NO_CHANGES = 0
EXIT_ERROR = 1
EXIT_DRIFT_DETECTED = 2

# Regex patterns for parsing terraform plan output
RESOURCE_ACTION_PATTERN = re.compile(
    r"^\s+#\s+(\S+)\s+(will be|must be|has been)\s+(\w+)"
)
RESOURCE_LINE_PATTERN = re.compile(
    r"^\s+[~+\-]\s+resource\s+\"(\w+)\"\s+\"(\w+)\""
)
PLAN_SUMMARY_PATTERN = re.compile(
    r"Plan:\s+(\d+)\s+to add,\s+(\d+)\s+to change,\s+(\d+)\s+to destroy"
)
CHANGE_BLOCK_PATTERN = re.compile(
    r"^\s+#\s+([\w._\[\]\"]+)\s+(will be|must be)\s+(\w+)"
)
ATTRIBUTE_CHANGE_PATTERN = re.compile(
    r"^\s+[~+-]\s+(\w[\w.]*)\s+=\s+"
)


class DriftChecker:
    """Runs Terraform plan against targets and detects drift.

    The checker iterates over configured targets, initializes Terraform
    if needed, runs plan with -detailed-exitcode, and parses the output
    to build structured drift results.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.detection = config.detection
        self._terraform_bin = self._resolve_terraform_binary()

    def _resolve_terraform_binary(self) -> str:
        """Locate the Terraform binary on the system."""
        binary = self.detection.terraform_binary
        # Check if it's an absolute path
        if os.path.isabs(binary) and os.path.isfile(binary):
            return binary
        # Otherwise rely on PATH
        return binary

    def run(self) -> DetectionRun:
        """Execute drift detection across all enabled targets.

        Returns:
            DetectionRun with results for each target/workspace combination.
        """
        detection_run = DetectionRun()
        targets = self.config.enabled_targets

        if not targets:
            logger.warning("No enabled targets found in configuration")
            detection_run.mark_completed()
            return detection_run

        logger.info("Starting drift detection for %d target(s)", len(targets))

        for target in targets:
            for workspace in target.workspaces:
                logger.info(
                    "Checking %s (workspace: %s)", target.path, workspace
                )
                result = self._check_target(target, workspace)
                detection_run.results.append(result)

                if result.has_drift:
                    logger.warning(
                        "Drift detected in %s [%s]: %d resource(s)",
                        target.path,
                        workspace,
                        result.total_drifted,
                    )
                elif result.error_message:
                    logger.error(
                        "Error checking %s [%s]: %s",
                        target.path,
                        workspace,
                        result.error_message,
                    )
                else:
                    logger.info("No drift in %s [%s]", target.path, workspace)

        detection_run.mark_completed()
        logger.info(
            "Detection complete: %d/%d targets have drift (%d total resources)",
            detection_run.targets_with_drift,
            detection_run.total_targets,
            detection_run.total_drifted_resources,
        )
        return detection_run

    def _check_target(
        self, target: TargetConfig, workspace: str
    ) -> DriftResult:
        """Run drift detection on a single target/workspace.

        Args:
            target: The target directory configuration.
            workspace: Terraform workspace to check.

        Returns:
            DriftResult with detected drift or error information.
        """
        result = DriftResult(
            directory=target.path,
            workspace=workspace,
        )

        target_path = target.resolved_path
        if not target_path.exists():
            result.error_message = f"Target directory does not exist: {target_path}"
            result.plan_exit_code = EXIT_ERROR
            return result

        try:
            # Initialize Terraform if configured
            if self.detection.init_before_plan:
                self._terraform_init(target_path, target)

            # Select workspace
            if workspace != "default":
                self._select_workspace(target_path, workspace)

            # Run plan and parse
            exit_code, plan_output = self._terraform_plan(target_path, target)
            result.plan_exit_code = exit_code
            result.plan_output = plan_output

            if exit_code == EXIT_DRIFT_DETECTED:
                result.drifted_resources = self._parse_plan_output(plan_output)
            elif exit_code == EXIT_ERROR:
                result.error_message = self._extract_error(plan_output)

        except subprocess.TimeoutExpired:
            result.error_message = (
                f"Terraform plan timed out after {self.detection.plan_timeout}s"
            )
            result.plan_exit_code = EXIT_ERROR
        except FileNotFoundError:
            result.error_message = (
                f"Terraform binary not found: {self._terraform_bin}"
            )
            result.plan_exit_code = EXIT_ERROR
        except Exception as exc:
            result.error_message = f"Unexpected error: {exc}"
            result.plan_exit_code = EXIT_ERROR
            logger.exception("Error checking target %s", target.path)

        return result

    def _terraform_init(
        self, target_path: Path, target: TargetConfig
    ) -> None:
        """Run terraform init in the target directory.

        Args:
            target_path: Resolved path to the Terraform directory.
            target: Target configuration with optional backend config.
        """
        cmd = [self._terraform_bin, "init", "-input=false", "-no-color"]

        if target.backend_config:
            cmd.extend(["-backend-config", target.backend_config])

        logger.debug("Running: %s in %s", " ".join(cmd), target_path)

        subprocess.run(
            cmd,
            cwd=str(target_path),
            capture_output=True,
            text=True,
            timeout=self.detection.plan_timeout,
            check=True,
        )

    def _select_workspace(self, target_path: Path, workspace: str) -> None:
        """Select or create a Terraform workspace.

        Args:
            target_path: Resolved path to the Terraform directory.
            workspace: Name of the workspace to select.
        """
        # Try selecting the workspace
        result = subprocess.run(
            [self._terraform_bin, "workspace", "select", workspace, "-no-color"],
            cwd=str(target_path),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(
                "Workspace '%s' not found, attempting to create", workspace
            )
            subprocess.run(
                [self._terraform_bin, "workspace", "new", workspace, "-no-color"],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

    def _terraform_plan(
        self, target_path: Path, target: TargetConfig
    ) -> Tuple[int, str]:
        """Run terraform plan with detailed exit code.

        Exit codes:
            0 = no changes (no drift)
            1 = error
            2 = changes detected (drift found)

        Args:
            target_path: Resolved path to the Terraform directory.
            target: Target configuration with optional var file.

        Returns:
            Tuple of (exit_code, plan_output).
        """
        cmd = [
            self._terraform_bin,
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
        ]

        if self.detection.refresh_only:
            cmd.append("-refresh-only")

        if target.var_file:
            cmd.extend(["-var-file", target.var_file])

        logger.debug("Running: %s in %s", " ".join(cmd), target_path)

        result = subprocess.run(
            cmd,
            cwd=str(target_path),
            capture_output=True,
            text=True,
            timeout=self.detection.plan_timeout,
        )

        # Combine stdout and stderr for full output
        full_output = result.stdout
        if result.stderr:
            full_output += "\n" + result.stderr

        return result.returncode, full_output

    def _parse_plan_output(self, output: str) -> List[DriftedResource]:
        """Parse terraform plan output to extract drifted resources.

        Identifies resource changes by looking for the plan summary and
        individual resource action lines in the plan output.

        Args:
            output: Raw terraform plan output text.

        Returns:
            List of DriftedResource objects describing each drift.
        """
        resources: List[DriftedResource] = []
        lines = output.split("\n")
        current_resource: Optional[dict] = None
        current_attributes: List[str] = []

        for i, line in enumerate(lines):
            # Match resource action lines like:
            # "# aws_s3_bucket.example will be updated in-place"
            # "# aws_instance.web must be replaced"
            change_match = CHANGE_BLOCK_PATTERN.match(line)
            if change_match:
                # Save previous resource if exists
                if current_resource:
                    resources.append(
                        self._build_drifted_resource(
                            current_resource, current_attributes
                        )
                    )

                address = change_match.group(1)
                action_word = change_match.group(3)
                drift_type = self._action_to_drift_type(action_word)

                # Extract resource type from address (e.g., "aws_s3_bucket" from "aws_s3_bucket.example")
                resource_type = address.split(".")[0] if "." in address else address

                current_resource = {
                    "address": address,
                    "resource_type": resource_type,
                    "drift_type": drift_type,
                }
                current_attributes = []
                continue

            # Match attribute change lines within a resource block
            if current_resource:
                attr_match = ATTRIBUTE_CHANGE_PATTERN.match(line)
                if attr_match:
                    current_attributes.append(attr_match.group(1))

        # Don't forget the last resource
        if current_resource:
            resources.append(
                self._build_drifted_resource(current_resource, current_attributes)
            )

        # Fallback: parse summary line if no individual resources found
        if not resources:
            resources = self._parse_from_summary(output)

        return resources

    def _build_drifted_resource(
        self, resource_data: dict, attributes: List[str]
    ) -> DriftedResource:
        """Build a DriftedResource from parsed data.

        Args:
            resource_data: Dict with address, resource_type, drift_type.
            attributes: List of changed attribute names.

        Returns:
            Constructed DriftedResource.
        """
        return DriftedResource(
            address=resource_data["address"],
            resource_type=resource_data["resource_type"],
            drift_type=resource_data["drift_type"],
            attribute_changes=attributes,
        )

    def _action_to_drift_type(self, action: str) -> DriftType:
        """Map Terraform action words to DriftType enum.

        Args:
            action: Action word from plan output (created, updated, destroyed, replaced).

        Returns:
            Corresponding DriftType.
        """
        mapping = {
            "created": DriftType.ADD,
            "updated": DriftType.CHANGE,
            "destroyed": DriftType.DESTROY,
            "replaced": DriftType.REPLACE,
            "read": DriftType.CHANGE,
        }
        return mapping.get(action.lower(), DriftType.CHANGE)

    def _parse_from_summary(self, output: str) -> List[DriftedResource]:
        """Fallback parser using the plan summary line.

        If individual resource parsing fails, extract counts from
        the summary line: "Plan: X to add, Y to change, Z to destroy"

        Args:
            output: Raw terraform plan output text.

        Returns:
            List of placeholder DriftedResource objects.
        """
        resources: List[DriftedResource] = []
        summary_match = PLAN_SUMMARY_PATTERN.search(output)

        if summary_match:
            add_count = int(summary_match.group(1))
            change_count = int(summary_match.group(2))
            destroy_count = int(summary_match.group(3))

            for i in range(add_count):
                resources.append(
                    DriftedResource(
                        address=f"unknown_resource.add_{i}",
                        resource_type="unknown",
                        drift_type=DriftType.ADD,
                    )
                )
            for i in range(change_count):
                resources.append(
                    DriftedResource(
                        address=f"unknown_resource.change_{i}",
                        resource_type="unknown",
                        drift_type=DriftType.CHANGE,
                    )
                )
            for i in range(destroy_count):
                resources.append(
                    DriftedResource(
                        address=f"unknown_resource.destroy_{i}",
                        resource_type="unknown",
                        drift_type=DriftType.DESTROY,
                    )
                )

        return resources

    def _extract_error(self, output: str) -> str:
        """Extract a meaningful error message from plan output.

        Args:
            output: Raw terraform plan output with errors.

        Returns:
            Extracted error message or generic fallback.
        """
        error_lines = []
        capture = False
        for line in output.split("\n"):
            if "Error:" in line or "error:" in line.lower():
                capture = True
            if capture:
                error_lines.append(line.strip())
                if len(error_lines) >= 5:
                    break

        if error_lines:
            return "\n".join(error_lines)
        return "Terraform plan exited with error (exit code 1)"
