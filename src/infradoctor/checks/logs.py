"""Access log analysis: traffic, errors, latency percentiles and error spikes."""

from __future__ import annotations

import heapq
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from infradoctor.report import ERROR, INFO, WARNING, Report

# 10.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /api/users?id=3 HTTP/1.1" 200 512 0.123
LINE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+) [^"]*" '
    r"(?P<status>\d{3}) \S+ (?P<latency>[\d.]+)"
)
TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


@dataclass(frozen=True)
class Entry:
    ip: str
    time: datetime
    method: str
    path: str
    status: int
    latency: float

    @property
    def is_error(self) -> bool:
        return self.status >= 500


def parse_line(line: str) -> Entry | None:
    match = LINE.match(line)
    if not match:
        return None
    try:
        time = datetime.strptime(match["time"], TIME_FORMAT)
        latency = float(match["latency"])
    except ValueError:  # right shape, impossible value (e.g. 32/Oct, or a latency of "1.2.3")
        return None
    return Entry(
        ip=match["ip"],
        time=time,
        method=match["method"],
        path=match["path"].split("?", 1)[0],
        status=int(match["status"]),
        latency=latency,
    )


def top_k(counts: dict[str, int], k: int) -> list[tuple[str, int]]:
    """The k largest counts using a min-heap of size k: O(n log k).

    The heap's root is the smallest of the current top k, so any new item
    only needs to beat that one to get in.
    """
    heap: list[tuple[int, str]] = []
    for key, count in counts.items():
        if len(heap) < k:
            heapq.heappush(heap, (count, key))
        elif count > heap[0][0]:
            heapq.heapreplace(heap, (count, key))
    return [(key, count) for count, key in sorted(heap, key=lambda item: (-item[0], item[1]))]


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile: the smallest value that at least p% of
    values are less than or equal to."""
    if not sorted_values:
        return 0.0
    rank = math.ceil(p / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


def worst_window(times: list[datetime], window: timedelta) -> tuple[int, datetime | None]:
    """Sliding window over sorted timestamps: the most events inside any
    span of `window`, and when that span starts."""
    best, best_start = 0, None
    left = 0
    for right, current in enumerate(times):
        while current - times[left] > window:
            left += 1
        if right - left + 1 > best:
            best, best_start = right - left + 1, times[left]
    return best, best_start


def analyse(entries: list[Entry], top: int = 5, window_minutes: int = 5) -> dict:
    latencies = sorted(e.latency for e in entries)
    error_times = sorted(e.time for e in entries if e.is_error)
    spike, spike_start = worst_window(error_times, timedelta(minutes=window_minutes))
    per_hour = Counter(e.time.strftime("%Y-%m-%d %H:00") for e in entries if e.is_error)
    return {
        "total": len(entries),
        "errors": len(error_times),
        "status": Counter(e.status for e in entries),
        "top_paths": top_k(Counter(e.path for e in entries), top),
        "top_ips": top_k(Counter(e.ip for e in entries), top),
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "errors_per_hour": sorted(per_hour.items()),
        "spike": spike,
        "spike_start": spike_start,
    }


def check_file(
    path: Path,
    top: int = 5,
    window_minutes: int = 5,
    max_error_rate: float = 0.05,
    max_p99: float = 1.0,
) -> Report:
    report = Report(f"Log report: {path}")
    entries, skipped = [], 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        entry = parse_line(line)
        if entry:
            entries.append(entry)
        else:
            skipped += 1

    if skipped:
        report.add(WARNING, f"{skipped} line(s) could not be parsed")
    if not entries:
        report.add(ERROR, "no valid log lines found")
        return report

    stats = analyse(entries, top, window_minutes)
    error_rate = stats["errors"] / stats["total"]

    lines = report.lines
    lines.append(f"Requests: {stats['total']:,}   5xx errors: {stats['errors']:,} ({error_rate:.1%})")
    lines.append("Status codes: " + ", ".join(f"{s}={n}" for s, n in sorted(stats["status"].items())))
    lines.append(f"Latency: p50={stats['p50']:.3f}s  p95={stats['p95']:.3f}s  p99={stats['p99']:.3f}s")
    lines.append("")
    lines.append(f"Top {top} endpoints:")
    lines.extend(f"  {count:>6}  {name}" for name, count in stats["top_paths"])
    lines.append(f"Top {top} clients:")
    lines.extend(f"  {count:>6}  {name}" for name, count in stats["top_ips"])
    if stats["errors_per_hour"]:
        lines.append("5xx errors per hour:")
        lines.extend(f"  {hour}  {count}" for hour, count in stats["errors_per_hour"])

    if error_rate > max_error_rate:
        report.add(ERROR, f"error rate {error_rate:.1%} is above the {max_error_rate:.0%} threshold")
    if stats["p99"] > max_p99:
        report.add(WARNING, f"p99 latency {stats['p99']:.3f}s is above the {max_p99}s threshold")
    if stats["spike"] > 1:
        start = stats["spike_start"].strftime("%Y-%m-%d %H:%M")
        report.add(INFO, f"worst error spike: {stats['spike']} errors within {window_minutes} min starting {start}")
    return report