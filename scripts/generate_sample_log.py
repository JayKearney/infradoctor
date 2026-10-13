"""Generate examples/access.log: a day of fake traffic with one incident.

Usage: python scripts/generate_sample_log.py > examples/access.log
"""

import random
import sys
from datetime import datetime, time, timedelta

random.seed(42)  # same output every run

PATHS = (
    ["/api/orders"] * 30
    + ["/api/users"] * 20
    + ["/api/auth/login"] * 12
    + ["/health"] * 25
    + ["/api/products"] * 15
    + ["/api/checkout"] * 6
)
CLIENTS = [f"10.0.{a}.{b}" for a in range(1, 4) for b in range(10, 16)] + ["203.0.113.7"] * 12
INCIDENT_START, INCIDENT_END = time(10, 30), time(10, 36)


def main() -> None:
    now = datetime(2026, 10, 10, 9, 0, 0)
    lines = []
    for _ in range(1200):
        now += timedelta(seconds=random.randint(1, 10))
        path = random.choice(PATHS)
        method = "POST" if path in ("/api/checkout", "/api/auth/login") else "GET"
        status = random.choices([200, 201, 304, 404, 500, 503], [80, 5, 5, 6, 3, 1])[0]
        latency = round(random.lognormvariate(-2.6, 0.6), 3)

        # The incident: checkout and orders fail and slow down for a few minutes.
        if INCIDENT_START <= now.time() <= INCIDENT_END and path in ("/api/checkout", "/api/orders"):
            status = random.choice([500, 502, 503, 200])
            latency = round(random.uniform(1.5, 4.0), 3)

        query = f"?id={random.randint(1, 999)}" if path == "/api/orders" else ""
        stamp = now.strftime("%d/%b/%Y:%H:%M:%S")
        lines.append(
            f'{random.choice(CLIENTS)} - - [{stamp} +0000] "{method} {path}{query} HTTP/1.1" '
            f"{status} {random.randint(200, 5000)} {latency}"
        )

    lines.insert(400, "this line is not in the expected format")
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()