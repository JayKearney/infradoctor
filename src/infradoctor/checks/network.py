"""Network checks: IPv4 validation and overlapping CIDR detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from infradoctor.report import ERROR, WARNING, Report


def parse_ipv4(address: str) -> int:
    """Convert a dotted IPv4 address to a 32-bit integer.

    Raises ValueError for anything that is not a strict IPv4 address.
    """
    parts = address.split(".")
    if len(parts) != 4:
        raise ValueError(f"{address!r}: expected 4 octets, got {len(parts)}")

    value = 0
    for part in parts:
        if not part.isdigit():
            raise ValueError(f"{address!r}: octet {part!r} is not a number")
        if len(part) > 1 and part[0] == "0":
            raise ValueError(f"{address!r}: octet {part!r} has a leading zero")
        octet = int(part)
        if octet > 255:
            raise ValueError(f"{address!r}: octet {octet} is out of range 0-255")
        value = (value << 8) | octet
    return value


def is_valid_ipv4(address: str) -> bool:
    try:
        parse_ipv4(address)
        return True
    except ValueError:
        return False


def format_ipv4(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


@dataclass(frozen=True)
class Cidr:
    name: str
    text: str
    start: int
    end: int
    aligned: bool

    @property
    def size(self) -> int:
        return self.end - self.start + 1


def parse_cidr(text: str, name: str = "") -> Cidr:
    """Parse '10.0.0.0/16' into its first and last address as integers."""
    if "/" not in text:
        raise ValueError(f"{text!r}: missing '/prefix'")
    address, prefix_text = text.split("/", 1)
    if not prefix_text.isdigit() or not 0 <= int(prefix_text) <= 32:
        raise ValueError(f"{text!r}: prefix must be a number between 0 and 32")

    prefix = int(prefix_text)
    ip = parse_ipv4(address)
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    start = ip & mask
    end = start | (~mask & 0xFFFFFFFF)
    return Cidr(name=name or text, text=text, start=start, end=end, aligned=(ip == start))


def find_overlaps(cidrs: list[Cidr]) -> list[tuple[Cidr, Cidr]]:
    """Return every pair of CIDRs that overlap.

    Two CIDR blocks are either disjoint or one contains the other, so after
    sorting by start (largest block first) a stack of "open" blocks is enough:
    every block still on the stack contains the current one.
    """
    ordered = sorted(cidrs, key=lambda c: (c.start, -c.end))
    open_blocks: list[Cidr] = []
    overlaps: list[tuple[Cidr, Cidr]] = []

    for current in ordered:
        while open_blocks and open_blocks[-1].end < current.start:
            open_blocks.pop()
        for outer in open_blocks:
            overlaps.append((outer, current))
        open_blocks.append(current)
    return overlaps


def merge_ranges(cidrs: list[Cidr]) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent ranges (the classic Merge Intervals)."""
    merged: list[tuple[int, int]] = []
    for c in sorted(cidrs, key=lambda c: c.start):
        if merged and c.start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], c.end))
        else:
            merged.append((c.start, c.end))
    return merged


def load_text(path: Path, report: Report) -> list[Cidr]:
    """Read 'name cidr' or 'cidr' lines; '#' starts a comment."""
    cidrs = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        name, text = (fields[0], fields[1]) if len(fields) >= 2 else ("", fields[0])
        try:
            cidrs.append(parse_cidr(text, name))
        except ValueError as exc:
            report.add(ERROR, f"{path.name} line {lineno}: {exc}")
    return cidrs


# resource "aws_vpc" "prod" {            -> starts a VPC block named aws_vpc.prod
#   cidr_block = "10.0.0.0/16"           -> its range
TF_RESOURCE = re.compile(r'^\s*resource\s+"(?P<type>[\w-]+)"\s+"(?P<name>[\w-]+)"')
TF_CIDR = re.compile(r'^\s*cidr_block\s*=\s*"(?P<cidr>[^"]+)"')
TF_VPC_TYPES = {"aws_vpc", "aws_vpc_ipv4_cidr_block_association"}


def load_terraform(path: Path, report: Report) -> list[Cidr]:
    """Pull VPC ranges out of a Terraform file.

    Only VPC-level ranges are compared: subnets sit inside their VPC by design,
    and AWS already rejects overlapping subnets within one VPC. What AWS does not
    stop is two separate VPCs overlapping, which breaks peering and Transit Gateway.
    """
    cidrs = []
    current = None
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0].split("//", 1)[0]
        resource = TF_RESOURCE.match(line)
        if resource:
            current = f"{resource['type']}.{resource['name']}" if resource["type"] in TF_VPC_TYPES else None
            continue
        match = TF_CIDR.match(line)
        if match and current:
            try:
                cidrs.append(parse_cidr(match["cidr"], current))
            except ValueError as exc:
                report.add(ERROR, f"{path.name} line {lineno}: {exc}")
    return cidrs


def load_cidrs(path: Path, report: Report) -> list[Cidr]:
    """Load ranges from a text file, a .tf file, or every .tf file in a directory."""
    if path.is_dir():
        files = sorted(path.rglob("*.tf"))
        if not files:
            raise ValueError(f"{path}: no .tf files found")
        return [cidr for tf in files for cidr in load_terraform(tf, report)]
    if path.suffix == ".tf":
        return load_terraform(path, report)
    return load_text(path, report)


def check_file(path: Path) -> Report:
    report = Report(f"Network check: {path}")
    cidrs = load_cidrs(path, report)

    for c in cidrs:
        if not c.aligned:
            report.add(
                WARNING,
                f"{c.name} ({c.text}) has host bits set; network is {format_ipv4(c.start)}/{c.text.split('/')[1]}",
            )

    for outer, inner in find_overlaps(cidrs):
        report.add(ERROR, f"{inner.name} ({inner.text}) overlaps {outer.name} ({outer.text})")

    total = sum(end - start + 1 for start, end in merge_ranges(cidrs))
    report.lines.append(f"Ranges checked:      {len(cidrs)}")
    report.lines.append(f"Addresses covered:   {total:,}")
    return report


def check_overlap(a: str, b: str) -> Report:
    report = Report(f"Overlap check: {a} vs {b}")
    try:
        first, second = parse_cidr(a), parse_cidr(b)
    except ValueError as exc:
        report.add(ERROR, str(exc))
        return report
    if find_overlaps([first, second]):
        report.add(ERROR, f"{a} and {b} overlap")
    else:
        report.lines.append(f"{a} and {b} do not overlap")
    return report


def check_addresses(addresses: list[str]) -> Report:
    report = Report("IP address validation")
    for address in addresses:
        try:
            parse_ipv4(address)
            report.lines.append(f"✔ {address}")
        except ValueError as exc:
            report.add(ERROR, str(exc))
    return report