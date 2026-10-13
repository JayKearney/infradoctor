"""Storage check: find duplicate files by content and report wasted space."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from infradoctor.report import WARNING, Report

CHUNK = 64 * 1024
PREVIEW = 4 * 1024


def walk_files(root: Path) -> list[Path]:
    """Recursively list regular files, skipping symlinks."""
    files: list[Path] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                files.extend(walk_files(Path(entry.path)))
            elif entry.is_file():
                files.append(Path(entry.path))
    return files


def file_hash(path: Path, limit: int | None = None) -> str:
    """SHA-256 of the file, or of only its first `limit` bytes."""
    digest = hashlib.sha256()
    remaining = limit
    with path.open("rb") as fh:
        while remaining is None or remaining > 0:
            size = CHUNK if remaining is None else min(CHUNK, remaining)
            chunk = fh.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def group_by(paths: list[Path], key) -> list[list[Path]]:
    """Group paths by key(path) and keep only groups with 2+ members."""
    groups: dict[object, list[Path]] = defaultdict(list)
    for path in paths:
        groups[key(path)].append(path)
    return [group for group in groups.values() if len(group) > 1]


def find_duplicates(root: Path, min_size: int = 1) -> list[list[Path]]:
    """Three passes, each cheaper than the next would be on all files:
    1. group by size (free: no reading),
    2. within each size group, hash only the first 4 KB,
    3. within what still matches, hash the whole file.
    """
    files = [p for p in walk_files(root) if p.stat().st_size >= min_size]
    duplicates: list[list[Path]] = []
    for same_size in group_by(files, lambda p: p.stat().st_size):
        for same_start in group_by(same_size, lambda p: file_hash(p, PREVIEW)):
            duplicates.extend(group_by(same_start, file_hash))
    return [sorted(group) for group in duplicates]


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def check_dir(root: Path, min_size: int = 1) -> Report:
    report = Report(f"Storage check: {root}")
    groups = sorted(find_duplicates(root, min_size), key=lambda g: -g[0].stat().st_size * (len(g) - 1))

    wasted_total = 0
    for number, group in enumerate(groups, start=1):
        size = group[0].stat().st_size
        wasted = size * (len(group) - 1)
        wasted_total += wasted
        report.add(WARNING, f"group {number}: {len(group)} identical files, {human_size(wasted)} wasted")
        report.lines.append(f"Group {number} ({human_size(size)} each):")
        report.lines.extend(f"  {path.relative_to(root)}" for path in group)
        report.lines.append("")

    report.lines.append(f"Duplicate groups: {len(groups)}")
    report.lines.append(f"Wasted space:     {human_size(wasted_total)}")
    return report