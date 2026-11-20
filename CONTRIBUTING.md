# Contributing

Thanks for your interest in improving the Ecuador open-data lakehouse.

## Development setup

Prerequisites: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
uv run lakehouse --version
uv run python scripts/dev.py check
```

`scripts/dev.py` is the cross-platform entry point for the quality gates:

| Task | What it runs |
| --- | --- |
| `check` | `lint`, `format --check`, `types`, `test` |
| `lint` | `ruff check .` |
| `format` | `ruff format --check .` |
| `types` | `mypy` (strict, `src/` only) |
| `test` | `pytest` (browser tests are excluded unless marked `e2e`) |
| `fix` | `ruff check --fix .` then `ruff format .` |

## Tests

- Write the failing test first, then the implementation.
- Tests must be deterministic and offline; an autouse fixture blocks every
  non-loopback socket connection.
- Scratch state belongs in `tmp_path` or `mktemp -d`, never in the repository.
- Never weaken, skip or delete a test to make the suite green.

Run the browser suite explicitly with `uv run pytest -m e2e` after
`uv run playwright install chromium`.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/) in English:
  `feat(cli): add serve command`, `fix(parsers): handle cp1252 SRI files`.
- Keep commits focused and reviewable (roughly 400 changed lines or fewer,
  generated data excluded).
- Do not add AI attribution or `Co-Authored-By` trailers.
- Every pull request must pass lint, type checks and the test matrix on Linux,
  Windows and macOS before merging.
