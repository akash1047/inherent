# API Rate Limiting Guide

Rate limiting protects our infrastructure and is applied per API key.
Free tier allows 100 requests/minute, Pro allows 1,000 requests/minute.
Every response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and
`X-RateLimit-Reset` headers. Exceeding the limit returns HTTP 429 with a
`retry_after` value in seconds. Implement exponential backoff on 429
responses, cache results when possible, and batch requests to reduce call
volume. Limits reset on a rolling 60-second window.
