"""Shared configuration defaults -- single source of truth (#132).

Both services accept an S3/object-store region override via an env var, but
each used to hardcode its OWN fallback default in its pydantic ``Settings``
class:

- ``inh-public-api-svc`` defaulted ``aws_s3_region`` to ``"eu-central-1"``.
- ``inh-ingestion-svc`` defaulted ``s3_region`` to ``"nbg1"`` (a Hetzner
  Object Storage location code -- not even the same naming scheme as an
  AWS-style region string).

A deployment that sets the region env var for only one service (or relies on
defaults during local dev / a bare ``uv run`` without docker-compose) silently
leaves the other service on its own, different default. Uploads then land in
one region/bucket while reads target another -- #132.

``DEFAULT_S3_REGION`` is now the ONE default both services' Settings classes
import, so the code-level fallback (used whenever the region env var is
unset) can never disagree between the two services again. This mirrors the
existing anti-drift pattern for Weaviate naming (see ``inh_contracts.naming``,
#12): put the single value here, have both services import it, and pin a
contract test on each side (``test_settings_region_contract.py``) so a future
hardcoded literal on either side fails CI instead of drifting silently.

The value matches the default already baked into the deployed stack
(``docker-compose.yml``, ``docker-compose.release.yml``, ``infra/server.tf``
and ``.env.example`` all default ``AWS_REGION`` to ``us-east-1``), so a
service now agrees with the documented, deployed default even when started
directly (e.g. tests, local ``uv run``) without compose's env injection.
"""

DEFAULT_S3_REGION = "us-east-1"
