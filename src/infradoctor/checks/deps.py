"""Dependency checks: unknown services, cycles, deploy order and blast radius."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from infradoctor.inventory import load_services
from infradoctor.report import ERROR, Report

Graph = dict[str, list[str]]


def build_graph(services: dict[str, dict]) -> Graph:
    """service -> list of services it depends on."""
    return {name: list(spec["depends_on"]) for name, spec in services.items()}


def find_cycle(graph: Graph) -> list[str] | None:
    """Depth-first search with three colours. Returns one cycle as a path,
    e.g. ['a', 'b', 'c', 'a'], or None if the graph is acyclic."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for dep in graph.get(node, []):
            if dep not in colour:
                continue  # unknown service, reported separately
            if colour[dep] == GREY:
                return stack[stack.index(dep):] + [dep]
            if colour[dep] == WHITE:
                cycle = visit(dep)
                if cycle:
                    return cycle
        stack.pop()
        colour[node] = BLACK
        return None

    for node in sorted(graph):
        if colour[node] == WHITE:
            cycle = visit(node)
            if cycle:
                return cycle
    return None


def deploy_order(graph: Graph) -> list[str]:
    """Kahn's algorithm: dependencies come before the services that need them.

    Raises ValueError if there is a cycle (some services never reach in-degree 0).
    """
    known = set(graph)
    remaining = {node: sum(1 for d in deps if d in known) for node, deps in graph.items()}
    dependents: Graph = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in known:
                dependents[dep].append(node)

    ready = deque(sorted(n for n, count in remaining.items() if count == 0))
    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for dependent in sorted(dependents[node]):
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)

    if len(order) != len(graph):
        raise ValueError("dependency cycle detected, no valid deploy order")
    return order


def blast_radius(graph: Graph, failed: str) -> dict[str, int]:
    """Breadth-first search over reversed edges: every service that depends,
    directly or indirectly, on `failed`, with its distance in hops."""
    dependents: Graph = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            dependents.setdefault(dep, []).append(node)

    distance = {failed: 0}
    queue = deque([failed])
    while queue:
        node = queue.popleft()
        for dependent in dependents.get(node, []):
            if dependent not in distance:
                distance[dependent] = distance[node] + 1
                queue.append(dependent)
    del distance[failed]
    return distance


def check_file(path: Path, impact: str | None = None) -> Report:
    report = Report(f"Dependency check: {path}")
    graph = build_graph(load_services(path))

    for node, deps in sorted(graph.items()):
        for dep in deps:
            if dep not in graph:
                report.add(ERROR, f"{node} depends on unknown service '{dep}'")

    cycle = find_cycle(graph)
    if cycle:
        report.add(ERROR, "circular dependency: " + " -> ".join(cycle))
    else:
        order = deploy_order(graph)
        report.lines.append("Deploy order:")
        report.lines.extend(f"  {i}. {name}" for i, name in enumerate(order, start=1))

    if impact:
        if impact not in graph:
            report.add(ERROR, f"unknown service '{impact}'")
        else:
            affected = blast_radius(graph, impact)
            report.lines.append("")
            report.lines.append(f"If '{impact}' goes down, {len(affected)} service(s) are affected:")
            for name, hops in sorted(affected.items(), key=lambda item: (item[1], item[0])):
                kind = "directly" if hops == 1 else f"{hops} hops away"
                report.lines.append(f"  - {name} ({kind})")
    return report