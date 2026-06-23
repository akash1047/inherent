# Releasing

This repository does not assume an automated release train.

## Versioning

- Service versions live in each service `pyproject.toml`.
- Bump versions only when the public behavior, packaging surface, or documented release unit changes in a meaningful way.
- Keep version changes scoped to the service that actually changed unless the whole repository release story changes.

## Release Checklist

1. Confirm README and service docs match the shipped behavior.
2. Run the offline release-acceptance suites in one shot:
   ```bash
   make release-check
   ```
   This runs `make check` plus the public-api `contract` + `security` suites and
   the ingestion `eval` + `failure_injection` suites. The slow Compose e2e gate
   is **not** part of this target — it runs in CI via `integration.yml` (or
   locally via `make dev` + `make test-integration`).
3. Confirm the latest `integration.yml` (Compose e2e gate) and coverage floors
   are green in CI.
4. Summarize user-visible changes in the release notes or tag message.
5. Tag from a clean commit history that does not include private planning artifacts.

The full set of gating suites, coverage floors, and the README-claim → test
mapping is in the
[release acceptance matrix](release_acceptance_matrix.md).

## Documentation Rule

Do not publish a release if the root README or service READMEs describe endpoints, ports, or workflows that the repository does not currently support.
