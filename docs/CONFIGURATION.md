# Configuration

All runtime configuration comes from environment variables with the
`LAKEHOUSE_` prefix, loaded by `config.Settings` (pydantic-settings). Values are
validated before any work starts; an invalid value produces a readable
`ConfigError` and exit code 2, never a traceback.

Precedence: an explicit CLI flag overrides the environment, and the environment
overrides the built-in default. Settings are cached per process with
`get_settings()`; start a new command after changing the environment.

## Environment variables

| Variable | Type | Default | Allowed values | Meaning |
| --- | --- | --- | --- | --- |
| `LAKEHOUSE_HOME` | path | platform-specific user data directory for `ecuador-lakehouse` | absolute path | Root for the warehouse, cache, dbt workspace, site and default artifact output |
| `LAKEHOUSE_MODE` | string | `sample` | `sample`, `full` | `sample` reads the bundled data offline; `full` downloads the pinned upstream files |
| `LAKEHOUSE_LOG_LEVEL` | string | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Minimum structlog level (case-insensitive input) |
| `LAKEHOUSE_LOG_FORMAT` | string | `console` | `console`, `json` | Human-readable or line-delimited JSON logs |
| `LAKEHOUSE_HTTP_TIMEOUT_S` | float | `30.0` | > 0 and <= 600 seconds | Per-request HTTP timeout |
| `LAKEHOUSE_HTTP_RETRIES` | integer | `3` | 0–10 | Retries for transient download failures, with exponential backoff |
| `LAKEHOUSE_SERVE_HOST` | string | `127.0.0.1` | loopback address | Interface for `lakehouse serve` |
| `LAKEHOUSE_SERVE_PORT` | integer | `15080` | 1024–65535 | Port for `lakehouse serve`; the 15000–15999 range avoids clashes with other local projects |
| `LAKEHOUSE_DBT_THREADS` | integer | `4` | 1–32 | dbt thread count passed to the transformer |
| `LAKEHOUSE_YEARS` | year selection | `2017-2026` | `2024`, `2019,2021-2022`, `2017-2026` | SRI partitions used by `build`, `fetch` and `sample build` |

`LAKEHOUSE_HOME` accepts a relative path, which is resolved against the
current working directory, but an absolute path is recommended. A missing
directory is created by the commands that need it.

`LAKEHOUSE_YEARS` is parsed as a comma-separated list of years and inclusive
ranges. Years must be between 2000 and 2100, the result is sorted and
de-duplicated, and an empty selection is rejected. It applies to SRI only:
BCE and INEC have a single fixed partition each.

## CLI overrides

These flags override the matching setting for one invocation:

| Command | Flag | Overrides |
| --- | --- | --- |
| `lakehouse serve` | `--host`, `--port`, `--open/--no-open` | `LAKEHOUSE_SERVE_HOST`, `LAKEHOUSE_SERVE_PORT` |
| `lakehouse fetch` | `--years` | `LAKEHOUSE_YEARS` for SRI only |
| `lakehouse fetch` | `--source`, `--accept-new-vintage` | not settings; selects the source and opts into a mutable vintage |
| `lakehouse sample build` | `--years` | `LAKEHOUSE_YEARS` |
| `lakehouse sample build` | `--cache-dir`, `--output-dir`, `--seed-dir` | cache and output locations (maintainer only) |
| `lakehouse build` | `--select`, `--only`, `--from-step`, `--publish`, `--out` | pipeline selection and artifact location |
| `lakehouse publish` | `--out` | artifact output directory |
| `lakehouse docs` | `--mermaid PATH` | also writes the Mermaid lineage file to `PATH` |
| `lakehouse contract check` | `--contract`, `--warehouse` | contract and warehouse paths |
| `lakehouse --debug` | — | show a full traceback for unexpected errors |

## Runtime home layout

Everything mutable lives under `LAKEHOUSE_HOME`; the repository and the
installed package stay read-only during a build.

```text
$LAKEHOUSE_HOME/
├── warehouse.duckdb          # raw, staging, intermediate, marts, meta
├── cache/
│   ├── sri_tax/              # verified upstream files (+ .part on resume)
│   ├── bce_cnt/
│   └── inec_cpi/
├── dbt/
│   ├── project/              # copy of the packaged dbt project
│   ├── target/               # run_results.json, manifest.json, docs
│   └── logs/
├── site/                     # generated static report + lineage/index.html
└── artifact/                 # default publish output for the library API
```

`lakehouse publish` and `lakehouse build --publish` default `--out` to
`./dist-artifact` so the artifact is easy to find; pass an explicit `--out` to
keep it inside the runtime home instead. Upstream downloads are cached under
`cache/` and never committed.

## Logging

`LAKEHOUSE_LOG_FORMAT=console` renders structured events for a terminal, while
`json` emits one object per line for ingestion:

```bash
LAKEHOUSE_LOG_LEVEL=DEBUG LAKEHOUSE_LOG_FORMAT=json lakehouse build
```

Every expected error is logged with its exit code. `lakehouse --debug` prints a
traceback for unexpected exceptions only; expected failures stay clean.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | success |
| 1 | unexpected exception |
| 2 | invalid configuration or command usage |
| 3 | checksum mismatch on an immutable source |
| 4 | source schema or archive error |
| 5 | source unavailable |
| 6 | dbt transformation failure |
| 7 | quality-gate failure |
| 8 | artifact verification or contract failure |

The full list and the error classes behind it are in
[ARCHITECTURE.md](ARCHITECTURE.md#failure-model-and-exit-codes).

## Examples

Offline sample build in an isolated home:

```bash
LAKEHOUSE_HOME="$(mktemp -d)" lakehouse build
```

Full mode against the real files, then a report on a different port:

```bash
LAKEHOUSE_MODE=full LAKEHOUSE_YEARS=2019-2026 lakehouse build
LAKEHOUSE_SERVE_PORT=15120 lakehouse serve --no-open
```

Reproducible JSON logs for a CI run:

```bash
LAKEHOUSE_LOG_FORMAT=json LAKEHOUSE_LOG_LEVEL=INFO lakehouse test
```

## Security notes

- No credential, token or account variable exists. The tool never asks for one.
- Downloads are limited to the hosts in `sources.lock.json`; redirects outside
  that allow-list are refused.
- Every download is capped in size and verified against a pinned SHA-256 before
  it is used.
- `lakehouse serve` is loopback-only by design and has no authentication; do not
  expose it on a public interface.
