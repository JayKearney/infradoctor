"""Network checks: IPv4 validation and overlapping CIDR detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from infradoctor.report import ERROR, INFO, WARNING, Report

# Put this in a comment on a range (or on its resource/module line) to say an
# overlap is intentional. An overlap is only allowed when BOTH ranges carry it.
ALLOW_MARKER = "infradoctor: allow-overlap"

# Ranges that clash with common defaults even without any peering.
RESERVED = [("Docker default bridge", "172.17.0.0/16")]


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
    file: str | None = None  # where it was defined, for annotations
    line: int | None = None
    allowed: bool = False  # marked with "# infradoctor: allow-overlap"
    known: bool = False  # from --known: defined outside this repo

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    @property
    def label(self) -> str:
        if self.known:
            return f"{self.name} ({self.text}, known range from {Path(self.file or '').name})"
        return f"{self.name} ({self.text})"


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


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].split("//", 1)[0]


def _allowed(raw: str) -> bool:
    return ALLOW_MARKER in raw.lower()


def load_text(path: Path, report: Report, known: bool = False) -> list[Cidr]:
    """Read 'name cidr' or 'cidr' lines; '#' starts a comment."""
    cidrs = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        name, text = (fields[0], fields[1]) if len(fields) >= 2 else ("", fields[0])
        try:
            cidr = parse_cidr(text, name)
        except ValueError as exc:
            report.add(ERROR, f"{path.name} line {lineno}: {exc}", str(path), lineno)
            continue
        cidrs.append(replace(cidr, file=str(path), line=lineno, allowed=_allowed(raw), known=known))
    return cidrs


# A top-level block:  resource "aws_vpc" "prod" {   module "vpc" {   locals {
TF_BLOCK = re.compile(
    r'^\s*(?P<kind>resource|module|data|variable|output|locals|provider|terraform)'
    r'(?P<labels>(?:\s+"[^"]*")*)\s*\{'
)
TF_LABEL = re.compile(r'"([^"]*)"')
TF_CIDR_BLOCK = re.compile(r'^\s*cidr_block\s*=\s*"(?P<cidr>[^"]+)"')  # aws_vpc and associations
TF_MODULE_CIDR = re.compile(r'^\s*cidr\s*=\s*"(?P<cidr>[^"]+)"')  # module "vpc" { cidr = ... }
TF_SECONDARY = re.compile(r'^\s*secondary_cidr_blocks\s*=\s*\[(?P<rest>.*)')
TF_VPC_TYPES = {"aws_vpc", "aws_vpc_ipv4_cidr_block_association"}


def _tf_range(path: Path, report: Report, text: str, name: str, lineno: int, allowed: bool) -> Cidr | None:
    try:
        cidr = parse_cidr(text, name)
    except ValueError as exc:
        report.add(ERROR, f"{path.name} line {lineno}: {exc}", str(path), lineno)
        return None
    return replace(cidr, file=str(path), line=lineno, allowed=allowed)


def load_terraform(path: Path, report: Report) -> list[Cidr]:
    """Pull VPC ranges out of a Terraform file.

    Reads `aws_vpc` and `aws_vpc_ipv4_cidr_block_association` resources, and
    modules with a `cidr` argument such as terraform-aws-modules/vpc (including
    `secondary_cidr_blocks`). Subnets are skipped: they sit inside their VPC by
    design, and AWS already rejects overlapping subnets within one VPC. What AWS
    does not stop is two separate VPCs overlapping.
    """
    found: list[tuple[str, str, int, bool]] = []  # (cidr text, name, line number, allowed)
    block = None  # e.g. "aws_vpc.prod" or "module.vpc"; None outside a VPC block
    block_allowed = False
    in_list = False  # inside a secondary_cidr_blocks list that spans several lines
    list_index = 0

    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = _strip_comment(raw)
        allowed = block_allowed or _allowed(raw)

        if in_list:
            for text in TF_LABEL.findall(line.split("]", 1)[0]):
                found.append((text, f"{block}.secondary_cidr_blocks[{list_index}]", lineno, allowed))
                list_index += 1
            in_list = "]" not in line
            continue

        start = TF_BLOCK.match(line)
        if start:
            labels = TF_LABEL.findall(start["labels"])
            block = None
            if start["kind"] == "resource" and len(labels) == 2 and labels[0] in TF_VPC_TYPES:
                block = f"{labels[0]}.{labels[1]}"
            elif start["kind"] == "module" and labels:
                block = f"module.{labels[0]}"
            block_allowed = _allowed(raw)
            continue
        if block is None:
            continue

        if block.startswith("module."):
            if match := TF_MODULE_CIDR.match(line):
                found.append((match["cidr"], block, lineno, allowed))
            elif match := TF_SECONDARY.match(line):
                rest = match["rest"]
                list_index = 0
                for text in TF_LABEL.findall(rest.split("]", 1)[0]):
                    found.append((text, f"{block}.secondary_cidr_blocks[{list_index}]", lineno, allowed))
                    list_index += 1
                in_list = "]" not in rest
        elif match := TF_CIDR_BLOCK.match(line):
            found.append((match["cidr"], block, lineno, allowed))

    cidrs = [_tf_range(path, report, *item) for item in found]
    return [c for c in cidrs if c is not None]


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


def _overlap(a: Cidr, b: Cidr) -> bool:
    return a.start <= b.end and b.start <= a.end


def check_file(path: Path, known: list[Path] | None = None) -> Report:
    report = Report(f"Network check: {path}")
    cidrs = load_cidrs(path, report)
    known_cidrs = [c for k in known or [] for c in load_text(k, report, known=True)]

    for c in cidrs:
        if not c.aligned:
            report.add(
                WARNING,
                f"{c.name} ({c.text}) has host bits set; network is {format_ipv4(c.start)}/{c.text.split('/')[1]}",
                c.file,
                c.line,
            )

    for outer, inner in find_overlaps(cidrs + known_cidrs):
        if outer.known and inner.known:
            continue  # both defined elsewhere: not this repo's problem
        # Report it from the side defined in this repo, so the annotation lands on our file.
        mine, other = (outer, inner) if inner.known else (inner, outer)
        message = f"{mine.label} overlaps {other.label}"
        if mine.allowed and other.allowed:
            report.add(INFO, f"{message} (allowed)", mine.file, mine.line)
        else:
            report.add(ERROR, message, mine.file, mine.line)

    for reserved_name, reserved_text in RESERVED:
        reserved = parse_cidr(reserved_text)
        for c in cidrs:
            if _overlap(c, reserved) and not c.allowed:
                report.add(
                    WARNING,
                    f"{c.label} overlaps the {reserved_name} ({reserved_text}); "
                    "containers on that network cannot reach these addresses",
                    c.file,
                    c.line,
                )

    total = sum(end - start + 1 for start, end in merge_ranges(cidrs))
    report.lines.append(f"Ranges checked:      {len(cidrs)}")
    if known_cidrs:
        report.lines.append(f"Known ranges:        {len(known_cidrs)}")
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