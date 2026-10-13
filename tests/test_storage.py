from infradoctor.checks.storage import check_dir, find_duplicates, human_size


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_finds_duplicates_across_folders(tmp_path):
    write(tmp_path / "a" / "one.bin", b"same content")
    write(tmp_path / "b" / "two.bin", b"same content")
    write(tmp_path / "c" / "deep" / "three.bin", b"same content")
    write(tmp_path / "unique.bin", b"different!!!")  # same size, different bytes
    groups = find_duplicates(tmp_path)
    assert len(groups) == 1
    assert {p.name for p in groups[0]} == {"one.bin", "two.bin", "three.bin"}


def test_same_start_but_different_end_is_not_a_duplicate(tmp_path):
    prefix = b"x" * 5000  # longer than the 4 KB preview
    write(tmp_path / "a.bin", prefix + b"A")
    write(tmp_path / "b.bin", prefix + b"B")
    assert find_duplicates(tmp_path) == []


def test_min_size_filter(tmp_path):
    write(tmp_path / "a.txt", b"hi")
    write(tmp_path / "b.txt", b"hi")
    assert find_duplicates(tmp_path, min_size=10) == []


def test_symlinks_are_ignored(tmp_path):
    write(tmp_path / "real.txt", b"content")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    assert find_duplicates(tmp_path) == []


def test_report_counts_wasted_space(tmp_path):
    for name in ("a", "b", "c"):
        write(tmp_path / f"{name}.dat", b"0123456789")
    report = check_dir(tmp_path)
    assert "Wasted space:     20 B" in report.lines
    assert not report.has_errors


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"