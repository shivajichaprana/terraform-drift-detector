# Terraform Drift Detector

Automated Terraform state drift detection with scheduled checks, alerting, and actionable reports.

## Overview

Infrastructure drift happens when someone makes a manual change in the cloud console, a deployment fails halfway, or an external process modifies resources outside of Terraform. This tool detects that drift by running `terraform plan -detailed-exitcode` against your configured workspaces on a schedule, parsing the output for resource-level changes, and generating reports with severity classification and notification support.

## Features

- **Multi-target scanning** — monitor multiple Terraform root modules and workspaces in a single run
- **Resource-level drift parsing** — identifies exactly which resources drifted and what changed
- **Severity classification** — automatic severity rating based on drift type and resource sensitivity
- **Multiple output formats** — console (with colors), JSON, and Markdown reports
- **Notification support** — Slack webhooks and email alerts when drift is detected
- **CI/CD integration** — `--exit-code` flag returns exit code 2 on drift for pipeline gating
- **Saved results** — JSON results persisted for historical tracking and re-reporting

## Quick Start

```bash
# Install
pip install -e .

# Copy and edit configuration
cp config.example.yaml config.yaml

# Run drift detection
drift-detector detect --config config.yaml

# Output as JSON
drift-detector detect --config config.yaml --output-format json

# Generate report from saved results
drift-detector report --input drift-results/drift-2026-04-23T06-00-00.json --format markdown

# CI mode: exit with code 2 if drift detected
drift-detector detect --config config.yaml --exit-code
```

## Configuration

See `config.example.yaml` for the full configuration reference. Key sections:

- **targets** — Terraform directories and workspaces to scan
- **detection** — plan timeout, parallelism, output format
- **notifications** — Slack webhook and email SMTP settings

## Project Structure

```
terraform-drift-detector/
├── detector/
│   ├── __init__.py          # Package metadata
│   ├── __main__.py          # Module entry point
│   ├── cli.py               # CLI with detect/report subcommands
│   ├── config.py            # YAML config loader
│   ├── drift_checker.py     # Core detection engine
│   ├── models.py            # Data models (DriftResult, DriftedResource)
│   ├── reporters/           # Output formatters (console, JSON, Markdown)
│   └── notifiers/           # Alert senders (Slack, email, GitHub Issues)
├── tests/                   # Unit and integration tests
├── scripts/                 # Helper scripts
├── .github/workflows/       # CI/CD and scheduled detection
├── config.example.yaml      # Example configuration
├── setup.py                 # Package setup
├── requirements.txt         # Python dependencies
└── LICENSE                  # MIT License
```

## Requirements

- Python >= 3.9
- Terraform CLI installed and configured
- Valid Terraform backend credentials for each target

## License

MIT
