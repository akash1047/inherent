"""Offline citation-support evals for the claim verifier (#39).

A small fixed set of (claim, evidence) -> expected verdict pairs. These pin the
lexical verifier's behaviour so a regression in src.services.verify is caught.
Offline; no services required; runs in the default ``-m 'not compose'`` suite.
"""

from __future__ import annotations

import pytest

from src.services.verify import verify_claim

pytestmark = pytest.mark.retrieval_eval


# Each case: (claim, evidence_list, expected_support_level).
CITATION_CASES: list[tuple[str, list[str], str]] = [
    (
        "The capital of France is Paris",
        ["Paris is the capital and most populous city of France."],
        "strong",
    ),
    (
        "Water boils at one hundred degrees Celsius at sea level",
        ["At sea level, water boils at one hundred degrees Celsius."],
        "strong",
    ),
    (
        "Photosynthesis converts sunlight into chemical energy",
        ["Photosynthesis is the process that converts sunlight into chemical energy in plants."],
        "strong",
    ),
    (
        "Quarterly revenue grew sharply in emerging markets",
        ["The quarterly report briefly mentions revenue trends in several markets."],
        "weak",
    ),
    (
        "The product launch was delayed until next spring",
        ["The product team released a statement about future roadmap plans."],
        "none",
    ),
    (
        "The Great Wall of China is visible from low orbit",
        ["Bananas are a good source of potassium and dietary fiber."],
        "none",
    ),
]


@pytest.mark.parametrize("claim, evidence, expected", CITATION_CASES)
def test_verify_claim_matches_expected(claim: str, evidence: list[str], expected: str) -> None:
    verdict = verify_claim(claim, evidence)
    assert verdict.support_level == expected, (
        f"claim={claim!r} expected {expected} but got "
        f"{verdict.support_level} (score={verdict.score}, reason={verdict.reason})"
    )
    assert 0.0 <= verdict.score <= 1.0


def test_strong_outranks_none() -> None:
    """A strongly-supported claim must score above an unsupported one."""
    strong = verify_claim(
        "Solar energy is renewable",
        ["Solar energy is a renewable energy source."],
    )
    none = verify_claim(
        "Solar energy is renewable",
        ["The recipe calls for two cups of flour and one egg."],
    )
    assert strong.score > none.score
    assert strong.support_level == "strong"
    assert none.support_level == "none"
