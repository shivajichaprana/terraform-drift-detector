"""
Shared pytest fixtures for drift detector tests.

Provides reusable mock Terraform plan outputs covering no-drift, single-change,
multi-resource drift, destroy operations, and error scenarios, plus mock
configuration files used across the test suite.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from detector.config import Config, DetectionConfig, TargetConfig
from detector.models import (
    DetectionRun,
    DriftedResource,
    DriftResult,
    DriftType,
)


# ---------------------------------------------------------------------------
# Terraform plan output fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def plan_output_no_drift() -> str:
    """Terraform plan output when no drift is present."""
    return dedent(
        """
        Refreshing Terraform state in-memory prior to plan...

        No changes. Your infrastructure matches the configuration.

        Terraform has compared your real infrastructure against your configuration
        and found no differences, so no changes are needed.
        """
    ).strip()


@pytest.fixture
def plan_output_single_change() -> str:
    """Plan output showing a single in-place change on an S3 bucket."""
    return dedent(
        """
        Terraform will perform the following actions:

          # aws_s3_bucket.example will be updated in-place
          ~ resource "aws_s3_bucket" "example" {
                id                          = "my-drift-bucket"
              ~ tags                        = {
                  ~ "Environment" = "dev" -> "prod"
                }
              ~ versioning {
                  ~ enabled = false -> true
                }
            }

        Plan: 0 to add, 1 to change, 0 to destroy.
        """
    ).strip()


@pytest.fixture
def plan_output_with_add() -> str:
    """Plan output showing a new resource that will be added."""
    return dedent(
        """
        Terraform will perform the following actions:

          # aws_instance.new_worker will be created
          + resource "aws_instance" "new_worker" {
              + ami           = "ami-12345"
              + instance_type = "t3.micro"
              + tags          = {
                  + "Name" = "worker-1"
                }
            }

        Plan: 1 to add, 0 to change, 0 to destroy.
        """
    ).strip()


@pytest.fixture
def plan_output_with_destroy() -> str:
    """Plan output showing a destructive change on a security group."""
    return dedent(
        """
        Terraform will perform the following actions:

          # aws_security_group.legacy will be destroyed
          - resource "aws_security_group" "legacy" {
              - id          = "sg-deadbeef" -> null
              - name        = "legacy-sg" -> null
              - description = "Legacy group" -> null
            }

        Plan: 0 to add, 0 to change, 1 to destroy.
        """
    ).strip()


@pytest.fixture
def plan_output_mixed_drift() -> str:
    """Plan output with add, change, and destroy operations combined."""
    return dedent(
        """
        Terraform will perform the following actions:

          # aws_instance.web will be updated in-place
          ~ resource "aws_instance" "web" {
              ~ instance_type = "t3.small" -> "t3.medium"
              ~ tags          = {
                  ~ "Environment" = "staging" -> "production"
                }
            }

          # aws_s3_bucket.logs will be created
          + resource "aws_s3_bucket" "logs" {
              + bucket = "drift-test-logs"
              + region = "us-east-1"
            }

          # aws_iam_role.old will be destroyed
          - resource "aws_iam_role" "old" {
              - name = "old-role" -> null
              - arn  = "arn:aws:iam::123:role/old-role" -> null
            }

        Plan: 1 to add, 1 to change, 1 to destroy.
        """
    ).strip()


@pytest.fixture
def plan_output_with_replace() -> str:
    """Plan output showing a resource that must be replaced."""
    return dedent(
        """
        Terraform will perform the following actions:

          # aws_db_instance.primary must be replaced
          -/+ resource "aws_db_instance" "primary" {
              ~ engine_version = "13.4" -> "14.2" # forces replacement
              ~ id             = "primary-db" -> (known after apply)
              ~ storage_type   = "gp2" -> "gp3"
            }

        Plan: 1 to add, 0 to change, 1 to destroy.
        """
    ).strip()


@pytest.fixture
def plan_output_error() -> str:
    """Plan output representing a Terraform error."""
    return dedent(
        """
        Initializing the backend...

        Error: Failed to get existing workspaces: S3 bucket does not exist.

          The referenced S3 bucket must have been previously created. If the S3
          bucket was created within the last minute, please wait for a minute or
          two and try again.


        Error: Error refreshing state: AccessDenied: Access Denied
            status code: 403, request id: ABC123
        """
    ).strip()


@pytest.fixture
def plan_output_summary_only() -> str:
    """Plan output where only a summary line is available (no per-resource block)."""
    return dedent(
        """
        Terraform will perform the following actions.

        Plan: 2 to add, 3 to change, 1 to destroy.
        """
    ).strip()


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_config_dict() -> dict:
    """Minimum viable config dictionary."""
    return {
        "targets": [
            {"path": "./infra/prod"},
        ],
    }


@pytest.fixture
def full_config_dict() -> dict:
    """Fully populated config dictionary covering all options."""
    return {
        "targets": [
            {
                "path": "./infra/prod",
                "workspaces": ["default", "production"],
                "var_file": "prod.tfvars",
                "backend_config": "backend-prod.conf",
                "enabled": True,
            },
            {
                "path": "./infra/staging",
                "workspaces": ["staging"],
                "enabled": False,
            },
        ],
        "detection": {
            "terraform_binary": "/usr/local/bin/terraform",
            "parallelism": 2,
            "init_before_plan": True,
            "refresh_only": True,
            "plan_timeout": 600,
            "save_results": True,
            "results_dir": "./results",
            "output_format": "markdown",
        },
        "notifications": {
            "slack": {
                "webhook_url": "https://hooks.slack.com/services/TEST/DRIFT",
                "channel": "#infra-alerts",
                "notify_on": "drift",
            },
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "alerts@example.com",
                "smtp_password": "secret",
                "from_address": "alerts@example.com",
                "to_addresses": ["ops@example.com"],
            },
        },
    }


@pytest.fixture
def config_file(tmp_path: Path, full_config_dict: dict) -> Path:
    """Write a full config to a temp YAML file and return the path."""
    import yaml

    config_path = tmp_path / "drift.yaml"
    config_path.write_text(yaml.safe_dump(full_config_dict))
    return config_path


@pytest.fixture
def minimal_config(minimal_config_dict: dict) -> Config:
    """Return a minimum Config object built from the minimal dict."""
    return Config.from_dict(minimal_config_dict)


@pytest.fixture
def full_config(full_config_dict: dict) -> Config:
    """Return a Config object built from the full dict."""
    return Config.from_dict(full_config_dict)


# ---------------------------------------------------------------------------
# Model / detection-run fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def drifted_resource_change() -> DriftedResource:
    """A single in-place change on a non-sensitive resource."""
    return DriftedResource(
        address="aws_s3_bucket.example",
        resource_type="aws_s3_bucket",
        drift_type=DriftType.CHANGE,
        attribute_changes=["tags", "versioning"],
    )


@pytest.fixture
def drifted_resource_destroy() -> DriftedResource:
    """A destructive change on a security-sensitive resource."""
    return DriftedResource(
        address="aws_iam_role.deleted",
        resource_type="aws_iam_role",
        drift_type=DriftType.DESTROY,
        attribute_changes=["name", "arn"],
    )


@pytest.fixture
def drift_result_with_drift(
    drifted_resource_change: DriftedResource,
    drifted_resource_destroy: DriftedResource,
) -> DriftResult:
    """A DriftResult holding two drifted resources."""
    return DriftResult(
        directory="./infra/prod",
        workspace="default",
        drifted_resources=[drifted_resource_change, drifted_resource_destroy],
        plan_exit_code=2,
    )


@pytest.fixture
def drift_result_clean() -> DriftResult:
    """A DriftResult with zero drifted resources."""
    return DriftResult(
        directory="./infra/staging",
        workspace="default",
        drifted_resources=[],
        plan_exit_code=0,
    )


@pytest.fixture
def drift_result_error() -> DriftResult:
    """A DriftResult representing a failed plan run."""
    return DriftResult(
        directory="./infra/broken",
        workspace="default",
        drifted_resources=[],
        plan_exit_code=1,
        error_message="Error: Failed to initialize backend",
    )


@pytest.fixture
def detection_run_with_drift(
    drift_result_with_drift: DriftResult,
    drift_result_clean: DriftResult,
) -> DetectionRun:
    """A DetectionRun with mixed drift and clean results."""
    run = DetectionRun(
        results=[drift_result_with_drift, drift_result_clean],
        config_file="drift.yaml",
    )
    run.mark_completed()
    return run


@pytest.fixture
def detection_run_clean(drift_result_clean: DriftResult) -> DetectionRun:
    """A DetectionRun with no drift."""
    run = DetectionRun(results=[drift_result_clean], config_file="drift.yaml")
    run.mark_completed()
    return run


@pytest.fixture
def detection_run_empty() -> DetectionRun:
    """A DetectionRun with no targets scanned."""
    run = DetectionRun(results=[], config_file=None)
    run.mark_completed()
    return run
