"""Health check response models."""

from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        ...,
        description="Component health status",
    )
    latency_ms: float | None = Field(
        default=None,
        description="Component response latency in milliseconds",
    )
    message: str | None = Field(
        default=None,
        description="Additional status message",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "latency_ms": 2.5,
                "message": None,
            }
        }
    }


class HealthResponse(BaseModel):
    """Full health check response with dependency status."""

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        ...,
        description="Overall service health status",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp of health check",
    )
    version: str = Field(
        ...,
        description="Service version",
    )
    service: str = Field(
        ...,
        description="Service name",
    )
    checks: dict[str, ComponentHealth] = Field(
        default_factory=dict,
        description="Health status of individual components",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "timestamp": "2024-01-08T12:00:00.000Z",
                "version": "0.1.0",
                "service": "inh-public-api-svc",
                "checks": {
                    "database": {"status": "healthy", "latency_ms": 2.5},
                    "weaviate": {"status": "healthy", "latency_ms": 15.0},
                },
            }
        }
    }


class LivenessResponse(BaseModel):
    """Simple liveness probe response."""

    status: Literal["healthy", "unhealthy"] = Field(
        ...,
        description="Service liveness status",
    )
    service: str = Field(
        ...,
        description="Service name",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "service": "inh-public-api-svc",
            }
        }
    }
