# API Authentication Guide

To authenticate requests, send an API key in the `X-API-Key` header or a
Bearer token in the `Authorization` header. Generate keys from the
dashboard; keys do not expire unless revoked. Bearer tokens are issued via
OAuth and expire after 24 hours, use a refresh token to get a new one.
Store credentials in environment variables, rotate keys regularly, and use
separate keys per environment. A 401 response means the key or token is
missing, invalid, or expired.
