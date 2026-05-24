# Releasing

This repository does not assume an automated release train.

## Versioning

- Service versions live in each service `pyproject.toml`.
- Bump versions only when the public behavior, packaging surface, or documented release unit changes in a meaningful way.
- Keep version changes scoped to the service that actually changed unless the whole repository release story changes.

## Release Checklist

1. Confirm README and service docs match the shipped behavior.
2. Run the documented checks for any changed service.
3. Review CI status.
4. Summarize user-visible changes in the release notes or tag message.
5. Tag from a clean commit history that does not include private planning artifacts.

## Documentation Rule

Do not publish a release if the root README or service READMEs describe endpoints, ports, or workflows that the repository does not currently support.
