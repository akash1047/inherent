"""Unit tests for the offline claim verifier (#39).

Pure/offline: no DB / MQ / network. Asserts the strong/weak/none verdicts and
score bounds for the lexical overlap strategy in src.services.verify.
"""

from __future__ import annotations

from src.services.verify import verify_claim


class TestVerifyClaimVerdicts:
    def test_strong_support_full_overlap(self) -> None:
        verdict = verify_claim(
            "The capital of France is Paris",
            ["Paris is the capital city of France and its largest city."],
        )
        assert verdict.support_level == "strong"
        assert verdict.score >= 0.6
        assert 0.0 <= verdict.score <= 1.0

    def test_weak_support_partial_overlap(self) -> None:
        # Claim keyphrases: revenue, grew, twenty, percent, third, quarter.
        # Evidence mentions only revenue + quarter -> partial overlap.
        verdict = verify_claim(
            "Revenue grew twenty percent in the third quarter",
            ["Total revenue figures are reported each quarter in the appendix."],
        )
        assert verdict.support_level == "weak"
        assert 0.25 <= verdict.score < 0.6

    def test_no_support_unrelated_evidence(self) -> None:
        verdict = verify_claim(
            "The Eiffel Tower is located in Paris",
            ["Photosynthesis converts sunlight into chemical energy in plants."],
        )
        assert verdict.support_level == "none"
        assert verdict.score < 0.25

    def test_empty_evidence_is_none(self) -> None:
        verdict = verify_claim("Any claim about something", [])
        assert verdict.support_level == "none"
        assert verdict.score == 0.0
        assert "No evidence" in verdict.reason

    def test_whitespace_only_evidence_is_none(self) -> None:
        verdict = verify_claim("Any claim about something", ["   ", ""])
        assert verdict.support_level == "none"
        assert verdict.score == 0.0

    def test_empty_claim_is_none(self) -> None:
        verdict = verify_claim("", ["Some evidence here about a topic."])
        assert verdict.support_level == "none"
        assert verdict.score == 0.0

    def test_stopword_only_claim_is_none(self) -> None:
        verdict = verify_claim("the and of to in on", ["the and of to in on at by"])
        assert verdict.support_level == "none"

    def test_best_evidence_wins(self) -> None:
        # One strong + several weak evidence strings -> verdict uses the best.
        verdict = verify_claim(
            "Solar panels convert sunlight into electricity",
            [
                "Unrelated text about cooking recipes.",
                "Solar panels convert sunlight directly into electricity efficiently.",
            ],
        )
        assert verdict.support_level == "strong"

    def test_score_is_bounded(self) -> None:
        verdict = verify_claim(
            "machine learning models require training data",
            ["machine learning models require large training data sets"],
        )
        assert 0.0 <= verdict.score <= 1.0
        assert verdict.support_level == "strong"

    def test_reason_is_populated(self) -> None:
        verdict = verify_claim("water boils at one hundred degrees", ["water boils at 100 degrees"])
        assert isinstance(verdict.reason, str)
        assert verdict.reason
