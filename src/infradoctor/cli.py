"""Command-line entry point: `infradoctor <check> ...`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from infradoctor import __version__
from infradoctor.checks import deps, logs, network, storage, versions
from infradoctor.report import emit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infradoctor",
        description="Audit common infrastructure hygiene issues.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    checks = parser.add_subparsers(dest="check", required=True, metavar="CHECK")

    p = checks.add_parser("logs", help="analyse an access log")
    p.add_argument("file", type=Path)
    p.add_argument("--top", type=int, default=5, help="how many top endpoints/clients to show")
    p.add_argument("--window", type=int, default=5, help="error spike window in minutes")
    p.add_argument("--max-error-rate", type=float, default=0.05, help="fail above this 5xx rate (0-1)")
    p.add_argument("--max-p99", type=float, default=1.0, help="warn above this p99 latency in seconds")

    p = checks.add_parser("network", help="validate IPs and detect overlapping CIDRs")
    net = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    # NEW: "check" now has a second option, --known
    c = net.add_parser("check", help="check Terraform or a file of CIDRs for overlaps")
    c.add_argument("file", type=Path, help="a .tf file, a folder of .tf files, or a CIDR text file")
    c.add_argument(
        "--known",
        type=Path,
        action="append",
        metavar="FILE",
        help="ranges defined outside this repo (CIDR text file); can be repeated",
    )
    net.add_parser("overlap", help="check whether two CIDRs overlap").add_argument("cidrs", nargs=2)
    net.add_parser("validate", help="validate IPv4 addresses").add_argument("addresses", nargs="+")

    p = checks.add_parser("storage", help="find duplicate files")
    p.add_argument("directory", type=Path)
    p.add_argument("--min-size", type=int, default=1, help="ignore files smaller than this (bytes)")

    p = checks.add_parser("versions", help="detect version drift between environments")
    p.add_argument("file", type=Path)
    p.add_argument("--max-minor-lag", type=int, default=2, help="warn when more minor versions behind")

    p = checks.add_parser("deps", help="check service dependencies")
    p.add_argument("file", type=Path)
    p.add_argument("--impact", metavar="SERVICE", help="show what breaks if SERVICE goes down")

    return parser


def run(args: argparse.Namespace):
    if args.check == "logs":
        return logs.check_file(args.file, args.top, args.window, args.max_error_rate, args.max_p99)
    if args.check == "network":
        if args.action == "check":
            return network.check_file(args.file, args.known)  # CHANGED: passes the --known files on
        if args.action == "overlap":
            return network.check_overlap(*args.cidrs)
        return network.check_addresses(args.addresses)
    if args.check == "storage":
        return storage.check_dir(args.directory, args.min_size)
    if args.check == "versions":
        return versions.check_file(args.file, args.max_minor_lag)
    return deps.check_file(args.file, args.impact)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except (OSError, ValueError) as exc:
        print(f"infradoctor: error: {exc}", file=sys.stderr)
        return 2
    return emit(report)


if __name__ == "__main__":
    sys.exit(main())