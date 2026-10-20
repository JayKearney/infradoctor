# Security and releases

- Third-party actions are pinned to full commit SHAs.
- The Action installs exact Python dependency versions from `action-requirements.txt`, kept current by Dependabot.
- Releases are immutable, and `v*` tags are protected by a ruleset.
- `@v1` always points to the latest `1.x` release. For maximum safety, pin to a release's commit SHA.

To report a vulnerability, see [SECURITY.md](https://github.com/JayKearney/infradoctor/blob/main/SECURITY.md).