# Documentation Site + Release Process Design

**Date:** 2026-07-14
**Status:** Approved
**Goal:** Give every consumer (operators, API/MCP integrators, contributors,
evaluators) a hosted documentation site with visible release notes, and make
release tagging + docs currency a mandatory, categorizable part of every change.

## Decisions (made with user)

1. **Site generator:** MkDocs Material on GitHub Pages (Python-native, zero
   Node toolchain, standard for Python OSS).
2. **Release visibility:** Changelog page on the site + published GitHub
   Releases per tag. Single "latest" docs version — no per-version snapshots
   (premature at v0.x).
3. **Work tagging:** Changelog-driven. Every behavior-changing PR adds a
   categorized `[Unreleased]` entry; cutting a release renames the section.
   No milestone/label tooling.
4. **Docs currency:** CLAUDE.md gains a rule that every change updates the
   affected docs in the same PR, so a release is a rename-and-publish step,
   never a documentation archaeology project.

## 1. Documentation site

### Layout

- `mkdocs.yml` at repo root, `docs_dir: docs`, `strict: true` link checking
  in CI via `mkdocs build --strict`.
- Material theme: dark/light toggle, search, navigation tabs, repo link,
  edit-this-page links to GitHub.
- Site deploys to GitHub Pages at the repository Pages URL.

### Navigation (existing files unless marked NEW)

| Tab | Pages |
| --- | --- |
| Home | NEW `docs/index.md` — landing page adapted from root README (what Inherent is, quickstart pointer, release badge) |
| Getting Started | `getting-started/local.md`, `getting-started/production.md`, `getting-started/local-vm-test.md` |
| Guides | `deploy/production.md` (hardening), `testing.md`, `advanced-indexes.md` |
| Reference | `examples/README.md` (curl examples), NEW `reference/rest-api.md` (endpoint reference), NEW `reference/mcp-tools.md` (tool reference), NEW `reference/configuration.md` (env-var reference) |
| Release Notes | `CHANGELOG.md` rendered on-site via a stub page using `pymdownx.snippets` (`--8<-- "CHANGELOG.md"`) so the root file stays the single source of truth |
| Architecture | `adr/README.md` + ADRs 0001–0003, `threat-models/rag-poisoning-injection.md` |
| Community | root `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md` rendered on-site (same include mechanism as CHANGELOG) |

Not in nav (built but unlisted; excluded from site search): `docs/audit/` test reports, `docs/maintainers/`
(linked from Community/Contributing prose, not a consumer tab),
`docs/superpowers/` specs/plans, `docs/developer/` internals (linked from
Contributing), `docs/examples/` non-Markdown assets (bruno, postman, scripts —
downloadable via GitHub links).

### New reference pages (the real consumer gap)

- `reference/rest-api.md`: every public REST endpoint — method, path,
  permission, request/response shape summary, links to curl examples.
  Source of truth: `services/inh-public-api-svc` routes + existing
  `docs/examples/README.md`.
- `reference/mcp-tools.md`: every MCP tool from the `_TOOLS` registry —
  name, permission, input schema summary, REST twin.
- `reference/configuration.md`: operator-facing env vars per service —
  name, default, effect (e.g. `EVAL_RETENTION_DAYS`,
  `EVAL_CAPTURE_DISABLED_WORKSPACES`, rate-limit toggles).

Rule: reference pages document only what exists in this repository (per
`docs/README.md` documentation rules).

### Deployment workflow

- `.github/workflows/docs.yml`:
  - PRs touching `docs/**`, `mkdocs.yml`, `CHANGELOG.md`, `*.md` at root:
    `mkdocs build --strict` (build-only check).
  - Push to `main`: build + deploy to GitHub Pages (official
    `actions/deploy-pages` flow).
- Pin mkdocs-material version in a `docs/requirements.txt` (or root
  `requirements-docs.txt`) for reproducible builds.

## 2. Release visibility

- Publish GitHub Releases for existing tags `v0.4.1` and `v0.5.0`, notes
  distilled from CHANGELOG.md: TL;DR bullets first, then
  Added/Changed/Fixed, then upgrade notes (new migrations, new env vars).
  Historical CHANGELOG entries are NOT rewritten.
- Changelog convention going forward: each release section leads with a 2–3
  bullet **TL;DR** before the Keep-a-Changelog categories.
- `docs/maintainers/releasing.md` gains steps: (a) move `[Unreleased]` →
  version+date with TL;DR, (b) publish GitHub Release from the changelog
  section, (c) verify the docs site deployed green.

## 3. CLAUDE.md changes

Add a **Release Tagging & Docs** section:

- Every merged PR that changes behavior, API surface, configuration, or
  deployment MUST add a one-line entry under `[Unreleased]` in
  `CHANGELOG.md` in a Keep-a-Changelog category
  (Added/Changed/Fixed/Deprecated/Removed/Security), ending with
  `(#PR, #issue)` refs. Docs-only, CI-only, and test-only changes are
  exempt. Cutting a release = renaming `[Unreleased]` — this is how all work
  is tagged to a release and categorized.
- Every change updates the docs it invalidates (site pages, reference pages,
  examples) in the same PR; the docs CI check must stay green. At release
  time the docs are already current — releasing is rename + tag + publish,
  never a catch-up docs sweep.

## 4. Testing / verification

- CI: `mkdocs build --strict` fails on broken nav entries or dead links.
- Local proof before PR: `mkdocs serve`, verify Home, one page per tab, and
  Release Notes render; capture evidence in the PR.
- GitHub Releases verified visible via `gh release list`.

## Out of scope

- Versioned docs snapshots (mike), separate docs repo, rewriting historical
  changelog entries, auto-generating reference pages from code (manual pages
  first; automation is a follow-up if drift becomes a problem).
