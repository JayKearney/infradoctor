"""Version drift: compare what each environment runs against the newest release."""

from __future__ import annotations

from pathlib import Path

from infradoctor.inventory import load_services
from infradoctor.report import ERROR, WARNING, Report


def parse_semver(text: str) -> tuple:
    """Turn '1.10.2', 'v2.0.0', '1.4.0-rc.1' or '1.31' into a tuple that sorts correctly.

    Plain string sorting gets versions wrong ('1.10.0' < '1.9.0' as strings),
    so we compare numbers, and a pre-release sorts before its final release.
    """
    text = str(text).strip().lstrip("v")
    core, _, prerelease = text.partition("-")
    parts = core.split(".")
    if len(parts) == 2:
        parts.append("0")  # Kubernetes/EKS style: '1.31' means '1.31.0'
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"{text!r} is not a MAJOR.MINOR[.PATCH] version")

    major, minor, patch = (int(p) for p in parts)
    if not prerelease:
        return (major, minor, patch, 1, ())

    identifiers = tuple(
        (0, int(item), "") if item.isdigit() else (1, 0, item) for item in prerelease.split(".")
    )
    return (major, minor, patch, 0, identifiers)


def latest(versions: list[str]) -> str:
    return max(versions, key=parse_semver)


def lag(current: str, newest: str) -> tuple[int, int]:
    """How far behind: (major versions, minor versions)."""
    cur, new = parse_semver(current), parse_semver(newest)
    if new[0] != cur[0]:
        return new[0] - cur[0], 0
    return 0, new[1] - cur[1]


def check_file(path: Path, max_minor_lag: int = 2) -> Report:
    report = Report(f"Version drift: {path}")
    services = load_services(path)

    rows = []
    for name, service in sorted(services.items()):
        envs: dict[str, str] = service.get("versions", {})
        if not envs:
            continue
        try:
            newest = latest(list(envs.values()))
        except ValueError as exc:
            report.add(ERROR, f"{name}: {exc}")
            continue

        rows.append(f"{name:<14} latest {newest:<12} " + "  ".join(f"{e}={v}" for e, v in envs.items()))
        for env, version in envs.items():
            majors, minors = lag(version, newest)
            if majors:
                report.add(ERROR, f"{name} in {env} is {majors} major version(s) behind ({version} vs {newest})")
            elif minors > max_minor_lag:
                report.add(WARNING, f"{name} in {env} is {minors} minor versions behind ({version} vs {newest})")

    report.lines.extend(rows)
    return report