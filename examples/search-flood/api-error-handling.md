# API Error Handling Guide

All errors return a JSON body with `error`, `message`, and `details`
fields. Common codes: 400 invalid request, 401 missing/invalid
authentication, 403 insufficient permission, 404 resource not found, 409
state conflict, 429 rate limit exceeded, 500 unexpected server error.
POST requests support an `Idempotency-Key` header so a retried request
returns the original cached result instead of creating a duplicate.
Default request timeout is 30 seconds; long-running operations return 202
Accepted with a status URL to poll.
