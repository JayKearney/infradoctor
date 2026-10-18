# Security policy

## Supported versions

Only the latest `1.x` release receives security fixes. When using the GitHub Action, `@v1` always points
to the latest `1.x` release.

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the problem and how to reproduce it.

This is a personal project maintained on a best-effort basis. Reports will be acknowledged as soon as
possible, and fixes released as a new `1.x` version.

## Scope

infradoctor reads local files (Terraform, YAML, logs, folders) and does not make network calls. Reports
about unsafe handling of untrusted input files, or about the GitHub Action (for example script injection
through its inputs), are especially welcome.