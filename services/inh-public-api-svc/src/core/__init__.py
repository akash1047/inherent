"""Core module containing exceptions, problem details, and rate limiter."""

from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    InherentAPIError,
    RateLimitError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from .problem_details import ProblemDetail, create_problem_detail
from .rate_limiter import RateLimitInfo, RateLimitResult, TokenBucketRateLimiter

__all__ = [
    # Exceptions
    "InherentAPIError",
    "AuthenticationError",
    "AuthorizationError",
    "RateLimitError",
    "ResourceNotFoundError",
    "ValidationError",
    "ServiceUnavailableError",
    "BadRequestError",
    # Problem Details
    "ProblemDetail",
    "create_problem_detail",
    # Rate Limiter
    "TokenBucketRateLimiter",
    "RateLimitResult",
    "RateLimitInfo",
]
