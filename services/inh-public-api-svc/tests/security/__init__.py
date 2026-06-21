"""Security regression test suite (#32).

These tests run fully offline: the database and search layers are mocked, so the
suite never needs the live compose stack. They guard the trust/tenancy
invariants that protect against cross-tenant data leakage and auth bypass.
"""
