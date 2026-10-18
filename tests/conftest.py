import pytest


@pytest.fixture(autouse=True)
def no_github_environment(monkeypatch):
    """Tests run inside GitHub Actions too. Without this, they would write to the
    real job summary and print annotations onto the real pull request."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)