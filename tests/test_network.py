import pytest

from infradoctor.checks.network import (
    check_file,
    find_overlaps,
    format_ipv4,
    is_valid_ipv4,
    merge_ranges,
    parse_cidr,
    parse_ipv4,
)


@pytest.mark.parametrize("address", ["0.0.0.0", "10.0.0.1", "192.168.1.255", "255.255.255.255"])
def test_valid_addresses(address):
    assert is_valid_ipv4(address)


@pytest.mark.parametrize(
    "address", ["", "1.2.3", "1.2.3.4.5", "256.0.0.1", "01.2.3.4", "1.2.3.a", "1..2.3", "-1.2.3.4", " 1.2.3.4"]
)
def test_invalid_addresses(address):
    assert not is_valid_ipv4(address)


def test_ipv4_round_trip():
    assert parse_ipv4("10.0.0.1") == 167772161
    assert format_ipv4(167772161) == "10.0.0.1"


def test_parse_cidr_range():
    cidr = parse_cidr("10.0.0.0/16")
    assert format_ipv4(cidr.start) == "10.0.0.0"
    assert format_ipv4(cidr.end) == "10.0.255.255"
    assert cidr.size == 65536
    assert cidr.aligned


def test_parse_cidr_host_bits_set():
    cidr = parse_cidr("192.168.1.10/24")
    assert not cidr.aligned
    assert format_ipv4(cidr.start) == "192.168.1.0"


@pytest.mark.parametrize("text", ["10.0.0.0", "10.0.0.0/33", "10.0.0.0/x", "300.0.0.0/8"])
def test_parse_cidr_invalid(text):
    with pytest.raises(ValueError):
        parse_cidr(text)


def test_find_overlaps_nested_and_disjoint():
    blocks = [parse_cidr(c) for c in ["10.0.0.0/16", "10.1.0.0/16", "10.0.128.0/24", "10.0.128.0/25"]]
    pairs = {(a.text, b.text) for a, b in find_overlaps(blocks)}
    assert pairs == {
        ("10.0.0.0/16", "10.0.128.0/24"),
        ("10.0.0.0/16", "10.0.128.0/25"),
        ("10.0.128.0/24", "10.0.128.0/25"),
    }


def test_no_overlaps():
    blocks = [parse_cidr(c) for c in ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/23"]]
    assert find_overlaps(blocks) == []


def test_merge_ranges_joins_adjacent_and_nested():
    blocks = [parse_cidr(c) for c in ["10.0.0.0/24", "10.0.1.0/24", "10.0.0.128/25", "10.0.5.0/24"]]
    merged = merge_ranges(blocks)
    assert [(format_ipv4(s), format_ipv4(e)) for s, e in merged] == [
        ("10.0.0.0", "10.0.1.255"),
        ("10.0.5.0", "10.0.5.255"),
    ]


TERRAFORM = """
resource "aws_vpc" "prod" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "prod_a" {
  vpc_id     = aws_vpc.prod.id
  cidr_block = "10.0.1.0/24"
}

resource "aws_vpc" "analytics" {
  cidr_block = "10.0.64.0/18" # overlaps prod
}

resource "aws_vpc" "shared" {
  // cidr_block = "10.0.0.0/8"  (commented out, must be ignored)
  cidr_block = var.shared_cidr
}
"""


def test_terraform_compares_vpcs_but_not_subnets(tmp_path):
    tf = tmp_path / "network.tf"
    tf.write_text(TERRAFORM)
    report = check_file(tf)
    errors = [f.message for f in report.findings if f.severity == "error"]
    assert errors == ["aws_vpc.analytics (10.0.64.0/18) overlaps aws_vpc.prod (10.0.0.0/16)"]
    assert "Ranges checked:      2" in report.lines


def test_terraform_directory_is_scanned_recursively(tmp_path):
    (tmp_path / "envs" / "prod").mkdir(parents=True)
    (tmp_path / "envs" / "prod" / "vpc.tf").write_text('resource "aws_vpc" "prod" {\n  cidr_block = "10.0.0.0/16"\n}\n')
    (tmp_path / "envs" / "dev.tf").write_text('resource "aws_vpc" "dev" {\n  cidr_block = "10.0.0.0/24"\n}\n')
    report = check_file(tmp_path)
    assert report.has_errors


def test_text_file_with_names_and_comments(tmp_path):
    cidrs = tmp_path / "cidrs.txt"
    cidrs.write_text("# comment\nprod 10.0.0.0/16\nstaging 10.1.0.0/16  # trailing comment\nbad 10.0.0.0/40\n")
    report = check_file(cidrs)
    assert [f.message for f in report.findings] == [
        "cidrs.txt line 4: '10.0.0.0/40': prefix must be a number between 0 and 32"
    ]