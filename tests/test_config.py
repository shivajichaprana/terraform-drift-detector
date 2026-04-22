"""
Unit tests for configuration loading and validation.

Covers YAML file parsing, dict-based construction, field defaults,
validation errors for malformed configs, and environment variable
fallback behavior for credential fields.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from detector.config import (
    Config,
    DetectionConfig,
    EmailConfig,
    SlackConfig,
    TargetConfig,
)


# ---------------------------------------------------------------------------
# TargetConfig
# ---------------------------------------------------------------------------


class TestTargetConfig:
    """Tests for TargetConfig.from_dict and resolved_path."""

    def test_minimal_target(self) -> None:
        target = TargetConfig.from_dict({"path": "./infra"})

        assert target.path == "./infra"
        assert target.workspaces == ["default"]
        assert target.var_file is None
        assert target.backend_config is None
        assert target.enabled is True

    def test_fully_specified_target(self) -> None:
        target = TargetConfig.from_dict({
            "path": "./infra/prod",
            "workspaces": ["prod", "prod-dr"],
            "var_file": "prod.tfvars",
            "backend_config": "backend-prod.conf",
            "enabled": False,
        })

        assert target.path == "./infra/prod"
        assert target.workspaces == ["prod", "prod-dr"]
        assert target.var_file == "prod.tfvars"
        assert target.backend_config == "backend-prod.conf"
        assert target.enabled is False

    def test_resolved_path_expands_user(self) -> None:
        target = TargetConfig(path="~/infra")
        resolved = target.resolved_path

        assert str(resolved).startswith("/")
        assert "~" not in str(resolved)

    def test_resolved_path_expands_env_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("INFRA_ROOT", "/opt/infrastructure")
        target = TargetConfig(path="$INFRA_ROOT/prod")

        assert "/opt/infrastructure/prod" in str(target.resolved_path)


# ---------------------------------------------------------------------------
# DetectionConfig
# ---------------------------------------------------------------------------


class TestDetectionConfig:
    """Tests for DetectionConfig defaults and from_dict."""

    def test_defaults(self) -> None:
        detection = DetectionConfig()

        assert detection.terraform_binary == "terraform"
        assert detection.parallelism == 1
        assert detection.init_before_plan is True
        assert detection.refresh_only is False
        assert detection.plan_timeout == 300
        assert detection.output_format == "console"

    def test_from_dict_overrides(self) -> None:
        detection = DetectionConfig.from_dict({
            "terraform_binary": "/usr/local/bin/terraform",
            "parallelism": 4,
            "refresh_only": True,
            "plan_timeout": 900,
            "output_format": "json",
        })

        assert detection.terraform_binary == "/usr/local/bin/terraform"
        assert detection.parallelism == 4
        assert detection.refresh_only is True
        assert detection.plan_timeout == 900
        assert detection.output_format == "json"


# ---------------------------------------------------------------------------
# Notification configs (Slack + Email)
# ---------------------------------------------------------------------------


class TestNotificationConfigs:
    """Tests for SlackConfig and EmailConfig parsing."""

    def test_slack_config_defaults(self, monkeypatch) -> None:
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        slack = SlackConfig.from_dict({})

        assert slack.webhook_url == ""
        assert slack.username == "Drift Detector"
        assert slack.notify_on == "drift"

    def test_slack_env_var_fallback(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/env-test")
        slack = SlackConfig.from_dict({})

        assert slack.webhook_url == "https://hooks.slack.com/env-test"

    def test_slack_explicit_overrides_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/env-test")
        slack = SlackConfig.from_dict({"webhook_url": "https://hooks.slack.com/explicit"})

        assert slack.webhook_url == "https://hooks.slack.com/explicit"

    def test_email_config_defaults(self) -> None:
        email = EmailConfig.from_dict({})

        assert email.smtp_port == 587
        assert email.use_tls is True
        assert email.subject_prefix == "[Drift Detector]"
        assert email.to_addresses == []

    def test_email_env_var_fallback(self, monkeypatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.env.example.com")
        monkeypatch.setenv("SMTP_USER", "envuser")
        monkeypatch.setenv("SMTP_PASSWORD", "envpass")

        email = EmailConfig.from_dict({})

        assert email.smtp_host == "smtp.env.example.com"
        assert email.smtp_user == "envuser"
        assert email.smtp_password == "envpass"


# ---------------------------------------------------------------------------
# Full Config
# ---------------------------------------------------------------------------


class TestConfig:
    """Tests for Config top-level parsing and validation."""

    def test_from_dict_minimal(self, minimal_config_dict: dict) -> None:
        config = Config.from_dict(minimal_config_dict)

        assert len(config.targets) == 1
        assert config.targets[0].path == "./infra/prod"
        assert config.slack is None
        assert config.email is None

    def test_from_dict_full(self, full_config_dict: dict) -> None:
        config = Config.from_dict(full_config_dict)

        assert len(config.targets) == 2
        assert config.detection.parallelism == 2
        assert config.detection.output_format == "markdown"
        assert config.slack is not None
        assert config.slack.channel == "#infra-alerts"
        assert config.email is not None
        assert config.email.to_addresses == ["ops@example.com"]

    def test_enabled_targets_filters_disabled(self, full_config_dict: dict) -> None:
        config = Config.from_dict(full_config_dict)

        assert len(config.targets) == 2
        assert len(config.enabled_targets) == 1
        assert config.enabled_targets[0].path == "./infra/prod"

    def test_from_file_loads_yaml(self, config_file: Path) -> None:
        config = Config.from_file(str(config_file))

        assert len(config.targets) == 2
        assert config.slack is not None

    def test_from_file_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Config.from_file(str(tmp_path / "does-not-exist.yaml"))

    def test_from_file_empty_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("")

        with pytest.raises(ValueError, match="empty"):
            Config.from_file(str(empty))

    def test_from_file_no_targets_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "no-targets.yaml"
        config_path.write_text(yaml.safe_dump({"detection": {}}))

        with pytest.raises(ValueError, match="at least one target"):
            Config.from_file(str(config_path))

    def test_validation_rejects_empty_target_path(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(yaml.safe_dump({"targets": [{"path": ""}]}))

        with pytest.raises(ValueError, match="'path' field"):
            Config.from_file(str(config_path))

    def test_validation_rejects_low_parallelism(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(
            yaml.safe_dump({
                "targets": [{"path": "./ok"}],
                "detection": {"parallelism": 0},
            })
        )

        with pytest.raises(ValueError, match="parallelism"):
            Config.from_file(str(config_path))

    def test_validation_rejects_short_timeout(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(
            yaml.safe_dump({
                "targets": [{"path": "./ok"}],
                "detection": {"plan_timeout": 10},
            })
        )

        with pytest.raises(ValueError, match="timeout"):
            Config.from_file(str(config_path))

    def test_validation_rejects_unknown_output_format(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(
            yaml.safe_dump({
                "targets": [{"path": "./ok"}],
                "detection": {"output_format": "xml"},
            })
        )

        with pytest.raises(ValueError, match="output format"):
            Config.from_file(str(config_path))

    def test_validation_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("targets: [unclosed")

        with pytest.raises(yaml.YAMLError):
            Config.from_file(str(bad))
