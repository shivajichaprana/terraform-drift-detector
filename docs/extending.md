# Extending the detector

The detector is designed so that adding a new output format (reporter) or a new alerting channel (notifier) is a one-file change. This guide walks through both extension points with a worked example and explains the patterns the existing code uses.

## Architecture recap

Three layers, composed by `cli.py`:

```
DriftChecker  ->  DetectionRun (models)  ->  Reporter  -> text output
                                         \
                                          -> Notifier -> external system
```

- **`DriftChecker`** runs `terraform plan` and builds immutable `DetectionRun` objects. You should almost never need to touch this layer for extension work — it's the "what does drift look like" layer, and the data model it produces is the stable contract downstream code depends on.
- **Reporters** convert a `DetectionRun` into a string in some format (console, JSON, Markdown today).
- **Notifiers** send a `DetectionRun` plus a pre-rendered report body somewhere (Slack, email, GitHub Issues today).

The reporter and notifier layers are both factory-based: each lives in its own subpackage with an `__init__.py` that exports a registry and a factory function (`get_reporter`, `get_notifier`). To add a new one, you drop a module next to the existing ones and register it in the factory.

## Adding a reporter

### 1. Understand the data model

Every reporter receives a `DetectionRun`. The relevant parts of the model:

```python
@dataclass
class DriftedResource:
    address: str              # e.g. "aws_s3_bucket.logs"
    resource_type: str        # e.g. "aws_s3_bucket"
    drift_type: DriftType     # ADD | CHANGE | DESTROY | REPLACE
    attribute_changes: list[str]
    before_value: str | None
    after_value: str | None

    @property
    def severity(self) -> Severity:  # LOW | MEDIUM | HIGH | CRITICAL

@dataclass
class DriftResult:
    target_path: str
    workspace: str
    drifted_resources: list[DriftedResource]
    has_drift: bool
    error: str | None
    duration_seconds: float

@dataclass
class DetectionRun:
    started_at: str           # ISO 8601
    finished_at: str
    results: list[DriftResult]
    config_file: str

    @property
    def has_drift(self) -> bool: ...
    @property
    def total_drifted_resources(self) -> int: ...
    @property
    def severity_counts(self) -> dict[Severity, int]: ...
```

All attributes are plain dataclasses — no side-effects, no lazy loading. You can traverse the run freely.

### 2. Write the reporter

Reporters live in `detector/reporters/`. Each one is a class with a `render(run: DetectionRun) -> str` method. By convention the class name ends in `Reporter`.

Here's a minimal HTML reporter as a worked example. Save as `detector/reporters/html_reporter.py`:

```python
"""HTML reporter — renders a self-contained HTML page with drift results."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import DetectionRun


class HtmlReporter:
    """Render a detection run as a static HTML page."""

    def __init__(self, include_css: bool = True) -> None:
        self.include_css = include_css

    def render(self, run: "DetectionRun") -> str:
        parts: list[str] = ["<!doctype html>", "<html>", "<head>"]
        parts.append("<meta charset='utf-8'>")
        parts.append("<title>Drift Detection Report</title>")
        if self.include_css:
            parts.append("<style>table{border-collapse:collapse}"
                         "td,th{border:1px solid #ccc;padding:4px 8px}</style>")
        parts.append("</head><body>")

        parts.append(f"<h1>Drift Detection — {escape(run.started_at)}</h1>")
        parts.append(f"<p><strong>{run.total_drifted_resources}</strong> "
                     f"drifted resources across {len(run.results)} targets.</p>")

        for result in run.results:
            parts.append(f"<h2>{escape(result.target_path)} "
                         f"({escape(result.workspace)})</h2>")
            if result.error:
                parts.append(f"<p style='color:red'>Error: "
                             f"{escape(result.error)}</p>")
                continue
            if not result.drifted_resources:
                parts.append("<p>No drift.</p>")
                continue
            parts.append("<table><tr><th>Resource</th><th>Type</th>"
                         "<th>Severity</th></tr>")
            for r in result.drifted_resources:
                parts.append(
                    f"<tr><td><code>{escape(r.address)}</code></td>"
                    f"<td>{escape(str(r.drift_type))}</td>"
                    f"<td>{escape(str(r.severity))}</td></tr>"
                )
            parts.append("</table>")

        parts.append("</body></html>")
        return "\n".join(parts)
```

### 3. Register it

Edit `detector/reporters/__init__.py` to add the new reporter to the registry:

```python
from .html_reporter import HtmlReporter

_REPORTERS = {
    "console": ConsoleReporter,
    "json": JsonReporter,
    "markdown": MarkdownReporter,
    "html": HtmlReporter,        # <-- added
}
```

Also add `HtmlReporter` to `__all__` and extend `ReporterType`.

### 4. Expose it on the CLI

Edit `detector/cli.py` and add `"html"` to the `choices` list on the `--output-format` argument (`detect` subcommand) and `--format` (`report` subcommand). That's it — the factory picks the new format up automatically.

### 5. Write a test

Every reporter has a test module under `tests/`. For HTML, `tests/test_html_reporter.py`:

```python
from detector.models import DetectionRun, DriftResult, DriftedResource, DriftType
from detector.reporters.html_reporter import HtmlReporter


def test_renders_empty_run():
    run = DetectionRun(
        started_at="2026-04-23T06:00:00Z",
        finished_at="2026-04-23T06:00:10Z",
        results=[],
        config_file="config.yaml",
    )
    html = HtmlReporter().render(run)
    assert "<html>" in html
    assert "0" in html  # total drifted resources


def test_renders_drift_with_escaping():
    resource = DriftedResource(
        address="aws_s3_bucket.<script>",
        resource_type="aws_s3_bucket",
        drift_type=DriftType.CHANGE,
    )
    result = DriftResult(
        target_path="./infra",
        workspace="default",
        drifted_resources=[resource],
        has_drift=True,
        duration_seconds=1.5,
    )
    run = DetectionRun(
        started_at="2026-04-23T06:00:00Z",
        finished_at="2026-04-23T06:00:10Z",
        results=[result],
        config_file="config.yaml",
    )
    html = HtmlReporter().render(run)
    assert "&lt;script&gt;" in html
    assert "<script>" not in html  # no unescaped tag
```

The important tests are: empty-run rendering, single-drift rendering, escaping untrusted strings (always a must for HTML). If your reporter has options (colors, verbosity, layout), add a test per option.

## Adding a notifier

### 1. Understand the contract

Every notifier is a class that accepts its configuration in the constructor and implements:

```python
def send(self, run: "DetectionRun", report_body: str) -> bool:
    """Send a notification about this run. Return True if sent, False if skipped/failed."""
```

`report_body` is a pre-rendered Markdown report, because Markdown is the lingua franca for Slack and GitHub. If your target accepts some other format, you can either use the Markdown as-is (Slack mrkdwn supports most of it) or re-render from the `run` using your own reporter inside the notifier.

The notifier should honour the shared `notify_on` semantics: `drift` means only send when `run.has_drift`, `error` means only send when any result has `.error`, `always` means always.

### 2. Write the notifier

Notifiers live in `detector/notifiers/`. A worked example — a PagerDuty notifier (`detector/notifiers/pagerduty_notifier.py`):

```python
"""PagerDuty notifier — creates an incident via Events API v2."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from ..models import DetectionRun

logger = logging.getLogger(__name__)

PAGERDUTY_URL = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyConfig:
    def __init__(self, routing_key: str, severity: str = "warning",
                 notify_on: str = "drift") -> None:
        self.routing_key = routing_key
        self.severity = severity
        self.notify_on = notify_on


class PagerDutyNotifier:
    """Create a PagerDuty incident when drift is detected."""

    def __init__(self, config: PagerDutyConfig) -> None:
        self.config = config

    def send(self, run: "DetectionRun", report_body: str) -> bool:
        # Respect notify_on
        if self.config.notify_on == "drift" and not run.has_drift:
            return False
        if self.config.notify_on == "error" and not any(r.error for r in run.results):
            return False

        if not self.config.routing_key:
            logger.warning("PagerDuty routing_key not set; skipping")
            return False

        payload = {
            "routing_key": self.config.routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": (
                    f"Terraform drift: {run.total_drifted_resources} "
                    f"resources across {len(run.results)} targets"
                ),
                "source": "terraform-drift-detector",
                "severity": self.config.severity,
                "custom_details": {"report": report_body[:1024]},
            },
        }

        try:
            response = requests.post(PAGERDUTY_URL, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("PagerDuty send failed: %s", exc)
            return False
```

### 3. Register it

Edit `detector/notifiers/__init__.py`:

```python
from .pagerduty_notifier import PagerDutyNotifier

_NOTIFIER_MAP = {
    "slack": ("slack", SlackNotifier),
    "email": ("email", EmailNotifier),
    "github": ("github", GitHubNotifier),
    "pagerduty": ("pagerduty", PagerDutyNotifier),   # <-- added
}
```

Add a branch to `get_notifier` that constructs the notifier from `config.pagerduty` (you'll also need to add a `PagerDutyConfig` load path to `detector/config.py`).

### 4. Add a config section

In `detector/config.py`, add a dataclass:

```python
@dataclass
class PagerDutyConfig:
    routing_key: str = ""
    severity: str = "warning"
    notify_on: str = "drift"

    @classmethod
    def from_dict(cls, data: dict) -> "PagerDutyConfig":
        return cls(
            routing_key=_expand(data.get("routing_key", "")),
            severity=data.get("severity", "warning"),
            notify_on=data.get("notify_on", "drift"),
        )
```

And wire it into the `Config` dataclass and its `from_dict` loader, then add the corresponding section to `config.example.yaml` so users can discover it.

### 5. Expose it on the CLI

Edit `detector/cli.py` and add `"pagerduty"` to the `choices` list on `--notify`.

### 6. Write a test

Notifier tests mock the transport:

```python
from unittest.mock import patch

from detector.models import DetectionRun
from detector.notifiers.pagerduty_notifier import PagerDutyNotifier, PagerDutyConfig


def _run(with_drift: bool = True) -> DetectionRun:
    # build a run fixture; see tests/conftest.py for the full helper
    ...


@patch("detector.notifiers.pagerduty_notifier.requests.post")
def test_triggers_incident_on_drift(mock_post):
    mock_post.return_value.status_code = 202
    notifier = PagerDutyNotifier(PagerDutyConfig(routing_key="abc123"))
    assert notifier.send(_run(with_drift=True), "report body")
    assert mock_post.called
    payload = mock_post.call_args.kwargs["json"]
    assert payload["event_action"] == "trigger"


@patch("detector.notifiers.pagerduty_notifier.requests.post")
def test_skips_on_clean_run(mock_post):
    notifier = PagerDutyNotifier(PagerDutyConfig(routing_key="abc123"))
    assert not notifier.send(_run(with_drift=False), "")
    assert not mock_post.called
```

The mandatory coverage: triggers on drift, skips on clean run (respecting `notify_on`), handles transport errors gracefully, refuses to send without credentials.

## Design notes

### Why factories instead of plugins?

Reporters and notifiers are bundled with the detector. We don't load them from entry points or arbitrary paths, because every one of them needs to reason about the `DetectionRun` model — and coordinating model changes across an unknown set of external plugins is painful.

If you find yourself adding 10+ notifiers, revisit this decision. For now, "one file per format, registered in the factory" is the sweet spot.

### Why Markdown as the notification lingua franca?

Slack accepts a subset of Markdown (mrkdwn). GitHub Issues accept Markdown natively. Email supports `text/plain` without any conversion. It's the lowest-common-denominator format that still conveys structure.

If you need a richer format for a specific channel (e.g. Slack Block Kit), your notifier can ignore the provided `report_body` and render its own from the `run`.

### Error handling

The rule of thumb:

- A reporter should _never_ raise — if it can't render a resource, it should render a placeholder string and keep going.
- A notifier _may_ return `False`, but it should not propagate exceptions to the caller. Log the exception and return `False`; the CLI already treats that as "notification failed" without terminating the run.

### Testing patterns

- **Reporters:** test against synthetic `DetectionRun` objects built in-test. Don't mock — the model is cheap to construct. Assert on the output string.
- **Notifiers:** always mock the transport (`requests.post`, `smtplib.SMTP`). Assert on the payload shape and on the `notify_on` branching.
- **Fixtures:** `tests/conftest.py` has helpers for building runs with drift, without drift, and with errors. Reuse them.

## Where to ask questions

Open a GitHub Discussion or Issue with the "question" label. Design-level questions (should this new thing be a reporter or a notifier?) are particularly welcome before you start coding.
