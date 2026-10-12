import pytest

from infradoctor.checks.versions import check_file, lag, latest, parse_semver


def test_numeric_not_string_ordering():
    assert parse_semver("1.10.0") > parse_semver("1.9.0")


def test_v_prefix_is_ignored():
    assert parse_semver("v2.0.0") == parse_semver("2.0.0")


def test_prerelease_sorts_before_release():
    assert parse_semver("2.0.0-rc.1") < parse_semver("2.0.0")
    assert parse_semver("2.0.0-rc.2") < parse_semver("2.0.0-rc.10")
    assert parse_semver("2.0.0-alpha") < parse_semver("2.0.0-beta")


@pytest.mark.parametrize("text", ["1", "1.2.3.4", "one.two.three", "1.x", ""])
def test_invalid_versions(text):
    with pytest.raises(ValueError):
        parse_semver(text)


def test_two_part_kubernetes_versions():
    assert parse_semver("1.31") == parse_semver("1.31.0")
    assert parse_semver("1.31") > parse_semver("1.9")
    assert lag("1.29", "1.31") == (0, 2)


def test_unquoted_float_version_is_rejected(tmp_path):
    inventory = tmp_path / "services.yaml"
    inventory.write_text("services:\n  eks:\n    versions: {dev: 1.30, prod: \"1.29\"}\n")
    with pytest.raises(ValueError, match="quote versions"):
        check_file(inventory)


def test_latest_and_lag():
    assert latest(["1.9.3", "1.10.0", "1.10.0-rc.1"]) == "1.10.0"
    assert lag("1.6.0", "1.10.0") == (0, 4)
    assert lag("1.9.0", "2.0.0") == (1, 0)
    assert lag("2.0.0", "2.0.0") == (0, 0)


def test_check_file_reports_drift(tmp_path):
    inventory = tmp_path / "services.yaml"
    inventory.write_text(
        "services:\n"
        "  api:\n"
        "    versions: {dev: 2.5.0, prod: 2.1.0}\n"
        "  db:\n"
        "    versions: {dev: 3.0.0, prod: 2.9.9}\n"
        "  cache:\n"
        "    versions: {dev: 1.1.0, prod: 1.0.0}\n"
    )
    report = check_file(inventory, max_minor_lag=2)
    messages = [(f.severity, f.message) for f in report.findings]
    assert ("warning", "api in prod is 4 minor versions behind (2.1.0 vs 2.5.0)") in messages
    assert ("error", "db in prod is 1 major version(s) behind (2.9.9 vs 3.0.0)") in messages
    assert not any("cache" in m for _, m in messages)