# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [1.2.1] - 2026-10-19

### Security
- The Action installs exact, tested versions of its Python dependencies (PyYAML and setuptools) from
  `action-requirements.txt`, instead of the newest version on PyPI.
- First immutable release: the `v1.2.1` tag can never be moved or deleted.

## [1.2.0] - 2026-10-18

### Added
- `--fail-on error|warning` option, and a `fail-on` input for the GitHub Action, so warnings can fail the run.
- Smoke test that checks the Action fails on a warning when `fail-on: warning` is set.

### Security
- The Action pins `actions/setup-python` to a full commit SHA.

## [1.1.0] - 2026-10-18

### Added
- `network`: reads VPCs created with the `terraform-aws-modules/vpc` module (`cidr` and `secondary_cidr_blocks`).
- `network`: `--known FILE` checks VPCs against ranges defined outside the repository.
- `network`: intentional overlaps can be marked with `# infradoctor: allow-overlap` on both ranges.
- `network`: warns when a VPC overlaps the Docker default bridge (`172.17.0.0/16`).
- Findings are shown as GitHub annotations on the exact file and line.

## [1.0.0] - 2026-10-16

### Added
- First release: `network`, `versions`, `deps`, `storage` and `logs` checks.
- GitHub Action with job summaries.

[1.2.1]: https://github.com/JayKearney/infradoctor/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/JayKearney/infradoctor/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/JayKearney/infradoctor/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/JayKearney/infradoctor/releases/tag/v1.0.0