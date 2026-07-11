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

## Publishing Images

The two custom services are published to the GitHub Container Registry so users
can run the stack without building:

- `ghcr.io/inherent-prime/ingestion-svc`
- `ghcr.io/inherent-prime/public-api-svc`

The other eight services in the stack are upstream OSS images and are **not**
republished — `docker-compose.release.yml` pulls them from their own public
registries. Consumers run the stack with that file (see the README
"Run from published images" section).

### Image tags vs. service versions

The published **image tag is a repository-level release version** taken from the
pushed git tag (`vX.Y.Z`). It is intentionally decoupled from the per-service
`pyproject.toml` versions, because one release publishes **both** images under a
single coordinated tag and `docker-compose.release.yml` selects them with one
`INHERENT_VERSION`. The service `pyproject.toml` versions remain independent
package versions and do not have to match the release tag.

### Approval gate (required, one-time setup)

`.github/workflows/publish.yml` builds both images on a `v*` tag, then the push
job is bound to the **`release-publish`** GitHub Environment. To make publishing
require human sign-off, configure that environment once in
**Settings → Environments → `release-publish` → Required reviewers** (add the
maintainers who may approve a publish). Until reviewers are configured the push
job runs without pausing.

### Cutting an image release

1. Complete the [Release Checklist](#release-checklist) above and merge the
   release commit to `main`.
2. Push a release-candidate tag, let CI build, then approve to publish:
   ```bash
   git tag vX.Y.Z-rc1 && git push origin vX.Y.Z-rc1   # candidate
   ```
   A `-rcN` tag publishes `:X.Y.Z-rcN` only — it never moves `:latest`.
3. When the candidate is accepted, push the final tag:
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z           # final
   ```
   A final (non-`rc`) tag publishes `:X.Y.Z`, `:X.Y`, and moves `:latest`.
4. In both cases, the workflow pauses on the `release-publish` environment until
   a reviewer approves the run in the **Actions** tab. Nothing is pushed to GHCR
   without that approval.
5. After a **successful** Publish images run on a **final** `vX.Y.Z` tag (not
   `-rcN`), [Hetzner e2e](../../.github/workflows/hetzner-e2e.yml) starts via
   `workflow_run`. It pins the same release for checkout, GHCR image tag
   `X.Y.Z`, and compose `compose_git_ref` (the tag). RC tags skip e2e.
6. Re-run manually: Actions → **Hetzner e2e** → **Run workflow**. Form fields
   and examples (Use workflow from vs `ref`, image tag, `cpx32`) live in
   [infra/README.md § Manual run](../../infra/README.md#manual-run-github-form).
   Short form: required `ref` (checkout + compose; must include `infra/`);
   optional `inherent_version` (GHCR tag; empty = strip leading `v` from `ref`);
   `server_type` default `cpx32`.

`make release-images` prints these steps.

### Hetzner / act e2e image parity

Hetzner e2e and local `act` pull **published**
`ghcr.io/inherent-prime/public-api-svc:${INHERENT_VERSION:-latest}` — not
workspace source.

If Weaviate has API-key auth enabled (release compose) but the image’s
`SearchService` does not send `Authorization: Bearer`, compose e2e fails with
public-api 500 / Weaviate 401. See
[`docs/audit/act-hetzner-e2e-weaviate-401.md`](../audit/act-hetzner-e2e-weaviate-401.md).

**Republish:** run workflow **Publish images** via `workflow_dispatch` (or push
a `v*` tag). Publish requires `release-publish` environment approval. Prefer
also republishing `ingestion-svc` in the same workflow run (matrix already
builds both).

**Smoke (required before re-running act):**

```bash
docker pull ghcr.io/inherent-prime/public-api-svc:latest
docker run --rm --entrypoint grep \
  ghcr.io/inherent-prime/public-api-svc:latest \
  -n 'Bearer {self._api_key}' \
  /app/services/inh-public-api-svc/src/services/search.py
```

Expect a matching line. No match → do not run Hetzner e2e; republish from
current `main` first.

## Documentation Rule

Do not publish a release if the root README or service READMEs describe endpoints, ports, or workflows that the repository does not currently support.
