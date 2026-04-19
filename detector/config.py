"""
Configuration loader for Terraform drift detection.

Reads YAML configuration files that define target directories,
workspaces, notification channels, and detection settings.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class TargetConfig:
    """Configuration for a single Terraform target directory."""

    path: str
    workspaces: List[str] = field(default_factory=lambda: ["default"])
    var_file: Optional[str] = None
    backend_config: Optional[str] = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "TargetConfig":
        """Create TargetConfig from a dictionary."""
        return cls(
            path=data["path"],
            workspaces=data.get("workspaces", ["default"]),
            var_file=data.get("var_file"),
            backend_config=data.get("backend_config"),
            enabled=data.get("enabled", True),
        )

    @property
    def resolved_path(self) -> Path:
        """Resolve the target path, expanding ~ and environment variables."""
        expanded = os.path.expandvars(os.path.expanduser(self.path))
        return Path(expanded).resolve()


@dataclass
class SlackConfig:
    """Slack notification settings."""

    webhook_url: str = ""
    channel: str = ""
    username: str = "Drift Detector"
    icon_emoji: str = ":warning:"
    notify_on: str = "drift"  # "always" | "drift" | "error"

    @classmethod
    def from_dict(cls, data: dict) -> "SlackConfig":
        """Create SlackConfig from a dictionary."""
        return cls(
            webhook_url=data.get("webhook_url", os.getenv("SLACK_WEBHOOK_URL", "")),
            channel=data.get("channel", ""),
            username=data.get("username", "Drift Detector"),
            icon_emoji=data.get("icon_emoji", ":warning:"),
            notify_on=data.get("notify_on", "drift"),
        )


@dataclass
class EmailConfig:
    """Email notification settings."""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    use_tls: bool = True
    from_address: str = ""
    to_addresses: List[str] = field(default_factory=list)
    subject_prefix: str = "[Drift Detector]"
    notify_on: str = "drift"

    @classmethod
    def from_dict(cls, data: dict) -> "EmailConfig":
        """Create EmailConfig from a dictionary."""
        return cls(
            smtp_host=data.get("smtp_host", os.getenv("SMTP_HOST", "")),
            smtp_port=data.get("smtp_port", 587),
            smtp_user=data.get("smtp_user", os.getenv("SMTP_USER", "")),
            smtp_password=data.get("smtp_password", os.getenv("SMTP_PASSWORD", "")),
            use_tls=data.get("use_tls", True),
            from_address=data.get("from_address", ""),
            to_addresses=data.get("to_addresses", []),
            subject_prefix=data.get("subject_prefix", "[Drift Detector]"),
            notify_on=data.get("notify_on", "drift"),
        )


@dataclass
class DetectionConfig:
    """Global detection settings."""

    terraform_binary: str = "terraform"
    parallelism: int = 1
    init_before_plan: bool = True
    refresh_only: bool = False
    plan_timeout: int = 300  # seconds
    save_results: bool = True
    results_dir: str = "./drift-results"
    output_format: str = "console"  # "console" | "json" | "markdown"

    @classmethod
    def from_dict(cls, data: dict) -> "DetectionConfig":
        """Create DetectionConfig from a dictionary."""
        return cls(
            terraform_binary=data.get("terraform_binary", "terraform"),
            parallelism=data.get("parallelism", 1),
            init_before_plan=data.get("init_before_plan", True),
            refresh_only=data.get("refresh_only", False),
            plan_timeout=data.get("plan_timeout", 300),
            save_results=data.get("save_results", True),
            results_dir=data.get("results_dir", "./drift-results"),
            output_format=data.get("output_format", "console"),
        )


@dataclass
class Config:
    """Top-level configuration for the drift detector."""

    targets: List[TargetConfig] = field(default_factory=list)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    slack: Optional[SlackConfig] = None
    email: Optional[EmailConfig] = None

    @property
    def enabled_targets(self) -> List[TargetConfig]:
        """Return only targets that are enabled."""
        return [t for t in self.targets if t.enabled]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Create Config from a parsed YAML dictionary."""
        targets = [TargetConfig.from_dict(t) for t in data.get("targets", [])]

        detection = DetectionConfig.from_dict(data.get("detection", {}))

        slack = None
        if "notifications" in data and "slack" in data["notifications"]:
            slack = SlackConfig.from_dict(data["notifications"]["slack"])

        email = None
        if "notifications" in data and "email" in data["notifications"]:
            email = EmailConfig.from_dict(data["notifications"]["email"])

        return cls(
            targets=targets,
            detection=detection,
            slack=slack,
            email=email,
        )

    @classmethod
    def from_file(cls, config_path: str) -> "Config":
        """Load configuration from a YAML file.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            Parsed Config object.

        Raises:
            FileNotFoundError: If the config file doesn't exist.
            yaml.YAMLError: If the file contains invalid YAML.
            ValueError: If required configuration fields are missing.
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not data:
            raise ValueError(f"Configuration file is empty: {config_path}")

        if "targets" not in data or not data["targets"]:
            raise ValueError(
                f"Configuration must define at least one target: {config_path}"
            )

        config = cls.from_dict(data)
        config._validate()
        return config

    def _validate(self) -> None:
        """Validate the configuration for common mistakes."""
        for target in self.targets:
            if not target.path:
                raise ValueError("Each target must have a 'path' field")

        if self.detection.parallelism < 1:
            raise ValueError("Detection parallelism must be >= 1")

        if self.detection.plan_timeout < 30:
            raise ValueError("Plan timeout must be >= 30 seconds")

        if self.detection.output_format not in ("console", "json", "markdown"):
            raise ValueError(
                f"Invalid output format: {self.detection.output_format}. "
                "Must be one of: console, json, markdown"
            )
