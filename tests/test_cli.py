from pathlib import Path

from infradoctor.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_exit_code_zero_when_clean(capsys):
    assert main(["network", "overlap", "10.0.0.0/16", "10.1.0.0/16"]) == 0
    assert "do not overlap" in capsys.readouterr().out


def test_exit_code_one_when_errors_found():
    assert main(["network", "check", str(EXAMPLES / "cidrs.txt")]) == 1


def test_exit_code_two_on_bad_input(tmp_path, capsys):
    assert main(["logs", str(tmp_path / "missing.log")]) == 2
    assert "infradoctor: error:" in capsys.readouterr().err


def test_writes_github_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    main(["deps", str(EXAMPLES / "services.yaml")])
    text = summary.read_text()
    assert text.startswith("## Dependency check")
    assert "Deploy order:" in text