from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    error: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ValidationErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    error: str = "validation_error"
    message: str
    details: list[dict[str, Any]]


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(cls, items: list[T], total: int, page: int, page_size: int) -> "PaginatedResponse[T]":
        total_pages = (total + page_size - 1) // page_size
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
    timestamp: datetime


class WebhookEvent(BaseModel):
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]
    signature: str | None = None
