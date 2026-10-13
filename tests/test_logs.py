from datetime import UTC, datetime, timedelta

from infradoctor.checks.logs import check_file, parse_line, percentile, top_k, worst_window

LINE = '10.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /api/users?id=3 HTTP/1.1" 503 512 0.123'


def test_parse_line():
    entry = parse_line(LINE)
    assert entry.ip == "10.0.0.1"
    assert entry.path == "/api/users"  # query string removed
    assert entry.status == 503 and entry.is_error
    assert entry.latency == 0.123
    assert entry.time == datetime(2026, 10, 10, 13, 55, 36, tzinfo=UTC)


def test_parse_line_rejects_garbage():
    assert parse_line("not a log line") is None
    assert parse_line(LINE.replace("10/Oct", "32/Oct")) is None  # impossible date
    assert parse_line(LINE.replace("0.123", "1.2.3")) is None  # impossible latency


def test_top_k_orders_by_count_then_name():
    counts = {"a": 5, "b": 9, "c": 1, "d": 9, "e": 3}
    assert top_k(counts, 3) == [("b", 9), ("d", 9), ("a", 5)]
    assert top_k(counts, 10)[-1] == ("c", 1)


def test_percentile_nearest_rank():
    values = [float(v) for v in range(1, 101)]  # 1..100
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 99) == 99
    assert percentile([0.5], 99) == 0.5
    assert percentile([], 50) == 0.0


def test_worst_window():
    base = datetime(2026, 1, 1, 12, 0)
    minutes = [0, 1, 2, 10, 11, 11, 12, 13, 30]
    times = [base + timedelta(minutes=m) for m in minutes]
    count, start = worst_window(times, timedelta(minutes=5))
    assert count == 5
    assert start == base + timedelta(minutes=10)


def test_check_file_thresholds(tmp_path):
    lines = []
    for second in range(10):
        status = 500 if second < 3 else 200
        latency = 2.5 if second == 9 else 0.05
        lines.append(
            f'10.0.0.{second} - - [10/Oct/2026:10:00:{second:02d} +0000] "GET /x HTTP/1.1" {status} 10 {latency}'
        )
    log = tmp_path / "access.log"
    log.write_text("\n".join(lines) + "\nbroken line\n")

    report = check_file(log, max_error_rate=0.05, max_p99=1.0)
    severities = {f.message.split()[0]: f.severity for f in report.findings}
    assert severities["error"] == "error"  # 30% error rate
    assert severities["p99"] == "warning"
    assert severities["1"] == "warning"  # 1 line(s) could not be parsed
    assert report.has_errors