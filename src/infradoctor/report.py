"""Shared reporting: findings, text output, GitHub job summaries and PR annotations."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ERROR = "error"
WARNING = "warning"
INFO = "info"

_ICONS = {ERROR: "✖", WARNING: "⚠", INFO: "ℹ"}

# GitHub Actions annotation level for each severity.
_ANNOTATION = {ERROR: "error", WARNING: "warning", INFO: "notice"}


@dataclass
class Finding:
    severity: str
    message: str
    file: str | None = None  # where the problem is, if it comes from a file
    line: int | None = None


@dataclass
class Report:
    title: str
    lines: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, message: str, file: str | None = None, line: int | None = None) -> None:
        self.findings.append(Finding(severity, message, file, line))

    @property
    def has_errors(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == WARNING for f in self.findings)

    def failed(self, fail_on: str = ERROR) -> bool:
        """Whether this report should fail the run: on errors, or also on warnings."""
        if fail_on == WARNING:
            return self.has_errors or self.has_warnings
        return self.has_errors

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


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _repo_relative(file: str) -> str:
    """Annotations need a path relative to the repository root."""
    workspace = os.environ.get("GITHUB_WORKSPACE")
    path = Path(file)
    if workspace and path.is_absolute():
        try:
            return path.relative_to(workspace).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def render_annotations(report: Report) -> list[str]:
    """GitHub workflow commands that show each finding as an annotation.

    Findings with a file and line appear on that exact line in the pull
    request's "Files changed" view.
    """
    commands = []
    for f in report.findings:
        props = ["title=infradoctor"]
        if f.file:
            props.append(f"file={_escape_property(_repo_relative(f.file))}")
            if f.line:
                props.append(f"line={f.line}")
        commands.append(f"::{_ANNOTATION[f.severity]} {','.join(props)}::{_escape_data(f.message)}")
    return commands


def emit(report: Report, fail_on: str = ERROR) -> int:
    """Print the report and, when running in GitHub Actions, add annotations and
    a job summary. Returns the process exit code: 1 if the report failed
    (errors, or also warnings with fail_on="warning"), otherwise 0."""
    print(report.render_text())
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for command in render_annotations(report):
            print(command)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(report.render_markdown())
    return 1 if report.failed(fail_on) else 0