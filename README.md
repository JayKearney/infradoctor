# infradoctor

[![CI](https://github.com/JayKearney/infradoctor/actions/workflows/ci.yml/badge.svg)](https://github.com/JayKearney/infradoctor/actions/workflows/ci.yml)

A small CLI that audits common infrastructure hygiene issues **before** they turn into incidents.
It reads the files platform teams already have (Terraform, service inventories, access logs,
artifact folders) and reports what needs fixing. Run it by hand, or as a gate in CI.

| Check | Finds | Typical use |
|---|---|---|
| `network` | Overlapping VPC ranges, invalid IPv4 addresses | Pull request gate on Terraform changes |
| `versions` | Environments drifting behind the latest release | Scheduled audit of image tags, EKS and add-on versions |
| `deps` | Unknown or circular service dependencies, safe deploy order, blast radius | PR gate on the service inventory; incident triage |
| `storage` | Duplicate files wasting disk or artifact storage | Cleanup audit of build agents and artifact stores |
| `logs` | Error rate, p50/p95/p99 latency, noisy clients, error spikes | Incident triage; post-deploy or load-test gate |

---

## Install

```bash
pip install git+https://github.com/JayKearney/infradoctor.git
```

Requires Python 3.11+. The only runtime dependency is PyYAML.

## Quick start

```bash
infradoctor network check examples/terraform          # every .tf file in a folder
infradoctor network overlap 10.0.0.0/16 10.0.128.0/24
infradoctor network validate 10.0.0.1 256.1.1.1
infradoctor versions examples/services.yaml
infradoctor deps examples/services.yaml --impact postgres
infradoctor storage examples/artifacts --min-size 1048576
infradoctor logs examples/access.log --max-error-rate 0.02 --max-p99 0.5
```

Every check has `--help`. `python -m infradoctor ...` works too.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Ran successfully, no errors (warnings allowed) |
| `1` | Ran successfully, **problems found** |
| `2` | Could not run: bad arguments or unreadable input |

Severities: **error** fails the run, **warning** is reported but does not fail, **info** is context.

---

## The checks

### `network`: overlapping VPCs and invalid addresses

**Why it matters.** AWS rejects overlapping subnets inside one VPC, but nothing stops two *separate*
VPCs from using overlapping ranges. That only surfaces later, when VPC peering or Transit Gateway
routing fails. Catching it on the pull request is far cheaper.

```text
$ infradoctor network check examples/terraform
Network check: examples/terraform
=================================
Ranges checked:      4
Addresses covered:   196,608

Findings:
  ✖ ERROR   aws_vpc.data_platform (10.0.128.0/20) overlaps aws_vpc.prod (10.0.0.0/16)
```

**How it works.**
- Reads `aws_vpc` and `aws_vpc_ipv4_cidr_block_association` ranges from `.tf` files (static analysis,
  nothing is applied). Subnets are skipped because they sit inside their VPC by design.
- Each IPv4 address is converted to a 32-bit integer; a CIDR becomes a `[start, end]` integer range
  using bit masks (`start = ip & mask`, `end = start | ~mask`).
- **Overlap detection:** CIDR blocks are either disjoint or nested, never partially overlapping. After
  sorting by start address (larger block first), a stack of "open" blocks is enough: every block still
  on the stack contains the current one. **O(n log n)** instead of comparing every pair (O(n²)).
- **Address space covered** merges the ranges first (the Merge Intervals pattern) so overlapping space
  is not double-counted.
- IPv4 validation is strict: exactly four octets, digits only, 0–255, no leading zeros.

### `versions`: version drift between environments

**Why it matters.** Environments fall out of sync: prod stays on an old image tag, an old add-on major,
or an old Kubernetes version. Old EKS versions move to extended support, which costs extra.

```text
$ infradoctor versions examples/services.yaml
...
Findings:
  ⚠ WARNING api-gateway in prod is 4 minor versions behind (2.0.5 vs 2.4.0)
  ⚠ WARNING eks-cluster in prod is 3 minor versions behind (1.28 vs 1.31)
  ✖ ERROR   orders in prod is 1 major version(s) behind (3.9.2 vs 4.0.0)
```

**How it works.**
- String sorting gets versions wrong (`"1.10.0" < "1.9.0"`), so each version becomes a tuple that sorts
  correctly: `(major, minor, patch, release-flag, pre-release identifiers)`.
- Follows SemVer precedence: pre-releases sort before their release (`4.0.0-rc.2 < 4.0.0`), numeric
  identifiers compare as numbers (`rc.2 < rc.10`). Two-part Kubernetes versions (`1.31`) are accepted.
- The newest version is found with `max(..., key=parse_semver)` in **O(n)**.
- A major version behind is an error; more than `--max-minor-lag` (default 2) minor versions is a warning.
- Unquoted YAML decimals (`1.30`, which YAML reads as the number `1.3`) are rejected with a clear
  message instead of silently producing a wrong version.

### `deps`: dependency graph checks

**Why it matters.** Circular dependencies mean no service can start first (a common failure when
rebuilding an environment or running a DR test). During an incident, the first question is
"what else is affected?"

```text
$ infradoctor deps examples/services.yaml --impact postgres
Dependency check: examples/services.yaml
========================================
Deploy order:
  1. eks-cluster
  2. kafka
  3. postgres
  4. redis
  5. notifications
  6. orders
  7. auth
  8. api-gateway
  9. frontend

If 'postgres' goes down, 4 service(s) are affected:
  - auth (directly)
  - orders (directly)
  - api-gateway (2 hops away)
  - frontend (3 hops away)

✔ No issues found
```

**How it works.** Services and their dependencies form a directed graph (adjacency list).
- **Cycle detection:** depth-first search with three colours (unvisited / in progress / done). Reaching
  an "in progress" node means a loop; the current DFS path is reported (`auth -> postgres -> auth`).
  Shared dependencies ("diamonds") are correctly *not* reported.
- **Deploy order:** topological sort with Kahn's algorithm: repeatedly deploy whatever has no
  undeployed dependencies left. This is the same ordering Terraform applies to its resource graph.
- **Blast radius:** breadth-first search over reversed edges, which also gives the shortest distance
  in hops.
- All three are **O(V + E)**.

### `storage`: duplicate files

**Why it matters.** Build agents, artifact stores and shared volumes accumulate identical copies of
large files under different names.

```text
$ infradoctor storage examples/artifacts
...
Duplicate groups: 2
Wasted space:     115 B
```

**How it works.** Comparing every pair of files is O(n²), so files are grouped by fingerprint in hash
maps, in three passes from cheapest to most expensive:
1. **Size** (metadata only, no reading). Files with a unique size are dropped.
2. **SHA-256 of the first 4 KB.**
3. **SHA-256 of the whole file**, read in 64 KB chunks so memory stays constant for large files.

This is the same content-addressing idea used by container image layers and Git. Symlinks are skipped
(no wasted space, and no infinite loops). `--min-size` ignores small files.

### `logs`: access log analysis

**Why it matters.** During an incident or after a deploy: when did errors start, which endpoint,
is one client hammering us, how slow is the tail?

```text
$ infradoctor logs examples/access.log
...
Latency: p50=0.073s  p95=0.234s  p99=3.168s
...
Findings:
  ⚠ WARNING 1 line(s) could not be parsed
  ✖ ERROR   error rate 5.1% is above the 5% threshold
  ⚠ WARNING p99 latency 3.168s is above the 1.0s threshold
  ℹ INFO    worst error spike: 14 errors within 5 min starting 2026-10-10 10:30
```

**How it works.**
- Each line is parsed with one compiled regex. Malformed lines (wrong shape, impossible dates) are
  counted and reported, never fatal. Query strings are stripped so `/api/orders?id=1` and
  `/api/orders?id=2` count as one endpoint.
- **Error rate** counts 5xx only (4xx are client errors).
- **Top endpoints / clients:** counts in a hash map, then a min-heap of size k: **O(n log k)**.
- **Percentiles** (p50/p95/p99) use the nearest-rank method on the sorted latencies. Percentiles rather
  than averages, because averages hide the slow tail.
- **Worst error spike:** a sliding window (two pointers) over sorted error timestamps finds the most
  errors in any `--window` minutes in **O(n)**.

---

## Use in GitHub Actions

```yaml
- uses: JayKearney/infradoctor@v1
  with:
    args: network check terraform/
```

The step fails when the check finds errors, and the report is added to the run's job summary.

## Input formats

**Terraform** (`network check`): a `.tf` file or a folder of them (searched recursively).

**CIDR file** (`network check`): one range per line, optionally named. `#` starts a comment.

```text
vpc-prod      10.0.0.0/16
vpc-staging   10.1.0.0/16
```

**Services inventory** (`versions`, `deps`):

```yaml
services:
  api-gateway:
    versions: {dev: 2.4.0, staging: 2.3.1, prod: 2.0.5}
    depends_on: [auth, orders]
  eks-cluster:
    versions: {dev: "1.31", staging: "1.31", prod: "1.28"}   # quote two-part versions
```

**Access log** (`logs`): combined log format with the response time in seconds as the last field:

```text
10.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /api/users HTTP/1.1" 200 512 0.123
```

## Design

```
 input files ──> readers ──> common model ──> checks ──> Report ──> text / job summary + exit code
 (.tf, YAML,     (one per     (CIDR ranges,    (pure      (findings
  logs, dirs)     format)      services graph)  functions) + severity)
```

- **Readers are separate from checks.** The algorithms only see a simple internal model, so a new input
  source (e.g. another log format) is a new reader, not a change to the algorithms.
- **Checks are pure functions** that return a `Report`; printing and exit codes live in one place.
  This keeps every check easy to unit test.
- **Fail clearly on bad input.** Unparseable input is either reported (log lines) or rejected with a
  clear message and exit code 2, never silently turned into a wrong answer.
- **Deterministic output.** Results are sorted so the same input always gives the same report,
  which matters for CI logs and diffs.
- **Untrusted input is read safely.** YAML is loaded with `yaml.safe_load`, since files may come from
  pull requests.

## Limitations and roadmap

- `network` reads literal `cidr_block` values; ranges set through variables (`var.vpc_cidr`) are not
  resolved. Reading `terraform show -json` plan output would cover them.
- `network` supports IPv4 only.
- `logs` supports one log format; ingress-nginx and AWS ALB formats need their own parsers.
- `logs` loads the whole file and sorts latencies; very large logs would need streaming and an
  approximate percentile structure (e.g. t-digest).
- Planned readers: dependencies from a Backstage catalog (`catalog-info.yaml` `spec.dependsOn`),
  and versions from Helm `values-<env>.yaml` files, instead of a hand-written inventory.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

`examples/access.log` is generated by `scripts/generate_sample_log.py`.

## License

MIT