from infradoctor.report import ERROR, INFO, WARNING, Report, emit, render_annotations


def test_annotations_with_file_and_line():
    report = Report("Network check")
    report.add(ERROR, "aws_vpc.data overlaps aws_vpc.prod", "terraform/vpcs.tf", 12)
    report.add(WARNING, "no location")
    report.add(INFO, "50% done, a: b\nnext line")
    assert render_annotations(report) == [
        "::error title=infradoctor,file=terraform/vpcs.tf,line=12::aws_vpc.data overlaps aws_vpc.prod",
        "::warning title=infradoctor::no location",
        "::notice title=infradoctor::50%25 done, a: b%0Anext line",
    ]


def test_annotation_paths_are_relative_to_the_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_WORKSPACE", "/home/runner/work/repo")
    report = Report("Network check")
    report.add(ERROR, "overlap", "/home/runner/work/repo/terraform/vpcs.tf", 3)
    assert render_annotations(report)[0].startswith("::error title=infradoctor,file=terraform/vpcs.tf,line=3::")


def test_annotations_only_printed_in_github_actions(monkeypatch, capsys):
    report = Report("Network check")
    report.add(ERROR, "overlap", "vpcs.tf", 3)
    assert emit(report) == 1
    assert "::error" not in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    emit(report)
    assert "::error title=infradoctor,file=vpcs.tf,line=3::overlap" in capsys.readouterr().out



def test_fail_on_warning():
    report = Report("Network check")
    report.add(WARNING, "overlaps the Docker default bridge")
    assert not report.failed()
    assert report.failed("warning")
    report.add(ERROR, "overlap")
    assert report.failed()