"""Load the services inventory (services.yaml) shared by the versions and deps checks."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_services(path: Path) -> dict[str, dict]:
    """Return {service_name: {"versions": {...}, "depends_on": [...]}}."""
    data = yaml.safe_load(path.read_text()) or {}
    services = data.get("services")
    if not isinstance(services, dict):
        raise ValueError(f"{path}: expected a top-level 'services:' mapping")

    normalised = {}
    for name, spec in services.items():
        spec = spec or {}
        versions = spec.get("versions") or {}
        for env, version in versions.items():
            if isinstance(version, float):
                # YAML reads an unquoted 1.30 as the number 1.3, losing the zero.
                raise ValueError(f"{path}: {name}.{env} = {version}: quote versions, e.g. \"1.30\"")
        normalised[str(name)] = {
            "versions": {str(env): str(v) for env, v in versions.items()},
            "depends_on": [str(d) for d in (spec.get("depends_on") or [])],
        }
    return normalised