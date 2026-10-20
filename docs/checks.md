# The checks

| Check | Finds |
|---|---|
| `network` | Overlapping VPC ranges in Terraform, clashes with known ranges, invalid IPv4 addresses |
| `versions` | Environments drifting behind the latest release |
| `deps` | Unknown or circular service dependencies, safe deploy order, blast radius |
| `storage` | Duplicate files wasting disk or artifact storage |
| `logs` | Error rate, p50/p95/p99 latency, noisy clients, error spikes |

## network

Reads `aws_vpc`, `aws_vpc_ipv4_cidr_block_association` and VPC modules with a `cidr` argument
(such as terraform-aws-modules/vpc). Overlaps are errors, unless both ranges are marked with
`# infradoctor: allow-overlap`. Use `--known FILE` for ranges defined outside the repository.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | No errors (warnings allowed) |
| `1` | Problems found (or warnings, with `--fail-on warning`) |
| `2` | Could not run: bad arguments or unreadable input |