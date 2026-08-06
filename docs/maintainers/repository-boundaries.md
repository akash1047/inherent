---
search:
  exclude: true
---

# Repository Boundaries

This repository should stay focused on the OSS core runtime.

## Keep In

- ingestion and public API code
- tests needed to validate OSS behavior
- local development infrastructure
- contributor-facing docs
- maintainer docs that help keep the OSS repository accurate

## Keep Out

- private planning artifacts
- maintainer-only tooling or workflows that contributors cannot access
- private deployment details and secrets
- private product applications or control-plane services
- documentation that implies unsupported hosted behavior

## Review Rule

When adding new docs or tooling, ask:

1. Can an external contributor understand and use this?
2. Does it describe behavior that actually exists in the repository?
3. Does it avoid leaking internal-only process?

If any answer is no, the change does not belong in the OSS repository in its current form.
