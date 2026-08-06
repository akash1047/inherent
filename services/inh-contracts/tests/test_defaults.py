"""Golden default-value test -- the package is the source of truth (#132).

DEFAULT_S3_REGION is the single default both services' Settings classes must
import for their S3/object-store region field. Pinning the literal here means
a future accidental edit to this constant is a visible, reviewed diff instead
of a silent redefinition on one service's side. See inh_contracts.defaults
for the full defect writeup.
"""

from inh_contracts import DEFAULT_S3_REGION
from inh_contracts.defaults import DEFAULT_S3_REGION as DEFAULT_S3_REGION_DIRECT


def test_default_s3_region_golden_value() -> None:
    """Pin the shared default so changing it is a deliberate, reviewed edit."""
    assert DEFAULT_S3_REGION == "us-east-1"


def test_default_s3_region_reexported_from_package_root() -> None:
    """The top-level ``inh_contracts`` re-export must match the module value."""
    assert DEFAULT_S3_REGION == DEFAULT_S3_REGION_DIRECT
