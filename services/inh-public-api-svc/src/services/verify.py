"""Offline claim-verification service (#39).

``verify_claim`` answers: *given a claim and some retrieved evidence, how well
does the evidence support the claim?* It is a deliberately simple, fully
offline, deterministic lexical strategy — no LLM, no network — so it is fast,
cheap, and unit-testable. (The MCP tool wrapper is M6 #40, not here.)

Strategy (documented)
---------------------
1. Tokenize the claim and each evidence string into lowercased word tokens,
   dropping a small English stopword set and tokens shorter than 2 chars.
2. The claim's *content tokens* are the keyphrases we look for.
3. For each evidence string compute the fraction of distinct claim content
   tokens that appear in that evidence (token-overlap recall). The verdict uses
   the BEST-supporting evidence string (max overlap), because a single strong
   source is enough to support a claim.
4. Map the best overlap score to a support level with documented thresholds:
       overlap >= 0.6            -> "strong"
       0.25 <= overlap < 0.6     -> "weak"
       overlap < 0.25            -> "none"
   Empty claim or no evidence -> "none" with score 0.0.

This favors *recall of the claim's keyphrases* over evidence length, so a long
passage that happens to contain the claim's key terms supports it, while
unrelated evidence does not. Score is the raw best-overlap in ``[0, 1]``.
"""

from __future__ import annotations

import re

from src.models.citation import SupportLevel, SupportVerdict

# Small, conservative English stopword set. Kept intentionally short so the
# verifier stays dependency-free and predictable.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "from",
        "into",
        "over",
        "under",
        "than",
        "so",
        "such",
        "no",
        "not",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "we",
        "you",
        "they",
        "he",
        "she",
        "i",
        "me",
        "my",
        "our",
        "your",
        "their",
        "his",
        "her",
        "them",
    }
)

# Documented thresholds for the support level (see module docstring).
_STRONG_THRESHOLD = 0.6
_WEAK_THRESHOLD = 0.25

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _content_tokens(text: str) -> set[str]:
    """Lowercase, tokenize, drop stopwords and 1-char tokens; return a set."""
    tokens = _TOKEN_RE.findall(text.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOPWORDS}


def verify_claim(claim: str, evidence: list[str]) -> SupportVerdict:
    """Verify how well ``evidence`` supports ``claim`` (offline, lexical).

    Args:
        claim: The natural-language claim to verify.
        evidence: Candidate supporting passages (e.g. retrieved chunk contents).

    Returns:
        A :class:`SupportVerdict` with ``support_level`` (strong/weak/none),
        ``score`` (best token-overlap in ``[0, 1]``), and a human ``reason``.
    """
    claim_tokens = _content_tokens(claim or "")

    if not claim_tokens:
        return SupportVerdict(
            support_level="none",
            score=0.0,
            reason="Claim has no content tokens to verify.",
        )

    non_empty_evidence = [e for e in (evidence or []) if e and e.strip()]
    if not non_empty_evidence:
        return SupportVerdict(
            support_level="none",
            score=0.0,
            reason="No evidence provided.",
        )

    best_overlap = 0.0
    best_matched: set[str] = set()
    for ev in non_empty_evidence:
        ev_tokens = _content_tokens(ev)
        matched = claim_tokens & ev_tokens
        overlap = len(matched) / len(claim_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_matched = matched

    score = round(best_overlap, 4)
    matched_count = len(best_matched)
    total = len(claim_tokens)

    level: SupportLevel
    if best_overlap >= _STRONG_THRESHOLD:
        level = "strong"
    elif best_overlap >= _WEAK_THRESHOLD:
        level = "weak"
    else:
        level = "none"

    reason = (
        f"Best evidence matched {matched_count}/{total} claim keyphrases "
        f"(overlap={score}); support level '{level}' "
        f"(thresholds: strong>={_STRONG_THRESHOLD}, weak>={_WEAK_THRESHOLD})."
    )

    return SupportVerdict(support_level=level, score=score, reason=reason)
