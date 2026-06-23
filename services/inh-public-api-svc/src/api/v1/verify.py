"""Claim-verification endpoint (#39).

POST /v1/verify-claim — given a claim and a list of evidence strings, return a
:class:`SupportVerdict` (strong/weak/none + score + reason). The verifier is
fully offline/lexical (see :mod:`src.services.verify`); the MCP tool wrapper is
M6 #40, not here.

Requires an API key with **read** permission.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.models.api_key import APIKeyInfo
from src.models.citation import SupportVerdict
from src.services.auth import get_read_permission
from src.services.verify import verify_claim
from src.utils import get_logger

router = APIRouter()
logger = get_logger(__name__)


class VerifyClaimRequest(BaseModel):
    """Request body for POST /v1/verify-claim."""

    claim: str = Field(..., min_length=1, max_length=2000, description="Claim to verify")
    evidence: list[str] = Field(
        default_factory=list,
        description="Candidate supporting passages (e.g. retrieved chunk contents)",
    )


@router.post("/verify-claim", response_model=SupportVerdict)
async def verify_claim_endpoint(
    request: VerifyClaimRequest,
    key_info: Annotated[APIKeyInfo, Depends(get_read_permission)],
) -> SupportVerdict:
    """Verify how well the supplied evidence supports the claim.

    Requires an API key with 'read' permission. Offline lexical strategy:
    token/keyphrase overlap mapped to strong/weak/none with a score.
    """
    verdict = verify_claim(request.claim, request.evidence)
    logger.info(
        "verify_claim",
        user_id=key_info.user_id,
        support_level=verdict.support_level,
        score=verdict.score,
        evidence_count=len(request.evidence),
    )
    return verdict
