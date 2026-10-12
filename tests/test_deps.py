import pytest

from infradoctor.checks.deps import blast_radius, check_file, deploy_order, find_cycle

GRAPH = {
    "frontend": ["api"],
    "api": ["auth", "db"],
    "auth": ["db"],
    "db": [],
    "worker": ["db"],
}


def test_deploy_order_puts_dependencies_first():
    order = deploy_order(GRAPH)
    position = {name: i for i, name in enumerate(order)}
    for service, deps in GRAPH.items():
        for dep in deps:
            assert position[dep] < position[service]


def test_no_cycle_in_valid_graph():
    assert find_cycle(GRAPH) is None


def test_cycle_is_detected_and_reported_as_path():
    graph = {"a": ["b"], "b": ["c"], "c": ["a"], "d": []}
    cycle = find_cycle(graph)
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}
    with pytest.raises(ValueError):
        deploy_order(graph)


def test_self_dependency_is_a_cycle():
    assert find_cycle({"a": ["a"]}) == ["a", "a"]


def test_blast_radius_with_distances():
    assert blast_radius(GRAPH, "db") == {"api": 1, "auth": 1, "worker": 1, "frontend": 2}
    assert blast_radius(GRAPH, "frontend") == {}


def test_check_file_flags_unknown_and_cycles(tmp_path):
    inventory = tmp_path / "services.yaml"
    inventory.write_text(
        "services:\n"
        "  a: {depends_on: [b]}\n"
        "  b: {depends_on: [a, ghost]}\n"
    )
    report = check_file(inventory)
    messages = [f.message for f in report.findings]
    assert "b depends on unknown service 'ghost'" in messages
    assert any(m.startswith("circular dependency:") for m in messages)
    assert report.has_errors