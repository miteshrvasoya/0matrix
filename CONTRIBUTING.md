# Contributing

## Development Setup

1. Clone repository.
2. Use Python 3.10+ for core development.
3. Optional: install Node 18+ and Go 1.21+ for SDK parity checks.

## Guidelines

- Keep the project serverless and storage-agnostic.
- Preserve the host/library boundary:
  - Host owns execution, DB, and metrics collection.
  - Library owns route selection logic only.
- Maintain deterministic behavior where required (tie-breakers and fixtures).
- Add tests for all behavior changes.

## Running Tests

GitHub Actions runs the same checks on every push and pull request.

```bash
python -m unittest discover -s tests -p "test_*.py"
node tests/node_parity.test.js
cd sdk/go && go test -modfile=go.ci.mod ./...
```

The Go job uses `sdk/go/go.ci.mod` because the checked-in `go.mod` still carries a publish-time placeholder module path.

## Pull Requests

- Describe strategy or API impact.
- Include before/after benchmark notes when changing algorithm behavior.
- Keep docs in sync with implementation.

## Versioning

Use semantic versioning:

- `MAJOR`: breaking API/behavior contracts
- `MINOR`: backward-compatible additions
- `PATCH`: fixes and non-breaking improvements
