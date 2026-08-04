"""Standalone visual report generation."""

from orbitops.reporting.benchmark_html import (
    ReportSelection,
    render_benchmark_html,
    write_benchmark_html,
    write_benchmark_html_from_json,
)

__all__ = [
    "ReportSelection",
    "render_benchmark_html",
    "write_benchmark_html",
    "write_benchmark_html_from_json",
]
