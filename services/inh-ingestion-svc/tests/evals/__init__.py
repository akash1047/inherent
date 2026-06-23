"""Fixture-backed extraction and chunking quality evaluations.

These evals run the real extraction and chunking code paths against the
sample documents in ``docs/examples/sample-documents`` and assert that the
output passes the production :class:`DataQualityService` checks. They are
offline (no live stack / databases required) and are marked with the
``eval`` pytest marker.
"""
