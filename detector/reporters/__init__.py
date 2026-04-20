"""
Report generators for drift detection results.

Provides a factory function to instantiate the appropriate reporter
based on output format selection. Supported formats: console, json, markdown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from .console_reporter import ConsoleReporter
from .json_reporter import JsonReporter
from .markdown_reporter import MarkdownReporter

if TYPE_CHECKING:
    from ..models import DetectionRun

ReporterType = Union[ConsoleReporter, JsonReporter, MarkdownReporter]

_REPORTERS = {
    "console": ConsoleReporter,
    "json": JsonReporter,
    "markdown": MarkdownReporter,
}


def get_reporter(fmt: str, **kwargs) -> ReporterType:
    """Factory function to create a reporter instance.

    Args:
        fmt: Output format name (console, json, markdown).
        **kwargs: Additional keyword arguments passed to the reporter constructor.

    Returns:
        An instantiated reporter.

    Raises:
        ValueError: If the format is not recognized.
    """
    reporter_cls = _REPORTERS.get(fmt)
    if reporter_cls is None:
        valid = ", ".join(sorted(_REPORTERS.keys()))
        raise ValueError(
            f"Unknown report format '{fmt}'. Valid formats: {valid}"
        )
    return reporter_cls(**kwargs)


def render_report(run: "DetectionRun", fmt: str = "console", **kwargs) -> str:
    """Convenience function to render a detection run in the given format.

    Args:
        run: The detection run to render.
        fmt: Output format (console, json, markdown).
        **kwargs: Additional options passed to the reporter.

    Returns:
        Formatted report string.
    """
    reporter = get_reporter(fmt, **kwargs)
    return reporter.render(run)


__all__ = [
    "ConsoleReporter",
    "JsonReporter",
    "MarkdownReporter",
    "get_reporter",
    "render_report",
]
