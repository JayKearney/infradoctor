"""Shared reporting: findings, text output and GitHub Actions job summaries."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"
INFO = "info"

_ICONS = {ERROR: "✖", WARNING: "⚠", INFO: "ℹ"}


@dataclass
class Finding:
    severity: str
    message: str


@dataclass
class Report:
    title: str
    lines: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, message: str) -> None:
        self.findings.append(Finding(severity, message))

    @property
    def has_errors(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)

    def render_text(self) -> str:
        out = [self.title, "=" * len(self.title)]
        out.extend(self.lines)
        if self.findings:
            out.append("")
            out.append("Findings:")
            for f in self.findings:
                out.append(f"  {_ICONS[f.severity]} {f.severity.upper():7} {f.message}")
        else:
            out.append("")
            out.append("✔ No issues found")
        return "\n".join(out)

    def render_markdown(self) -> str:
        out = [f"## {self.title}", ""]
        if self.lines:
            out.append("```")
            out.extend(self.lines)
            out.append("```")
        if self.findings:
            out.append("| Severity | Finding |")
            out.append("|---|---|")
            for f in self.findings:
                out.append(f"| {_ICONS[f.severity]} {f.severity} | {f.message} |")
        else:
            out.append("✔ No issues found")
        return "\n".join(out) + "\n"


def emit(report: Report) -> int:
    """Print the report, write a GitHub job summary if running in Actions,
    and return the process exit code (1 if any errors were found)."""
    print(report.render_text())
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(report.render_markdown())
    return 1 if report.has_errors else 0