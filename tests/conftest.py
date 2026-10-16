import pytest


@pytest.fixture(autouse=True)
def no_github_summary(monkeypatch):
    """Tests must not write into the real CI job summary."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)