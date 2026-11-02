# Contributing

Issues and pull requests are welcome.

- New rules must ship with a `rules-docs/<ID>.md` page plus `bad` and `good` fixtures under `tests/fixtures/` (the test suite checks this).
- Keep false positives low: if a pattern is only sometimes a problem, use `warn` or `info` and say when it is fine in the rule doc.
- Run `ruff check .`, `mypy`, and `pytest` before opening a PR.
- Add a line to `CHANGELOG.md` under `[Unreleased]`.
- Do not add AI-tool attribution trailers to commits.
