"""Pagination helper shared by list endpoints."""

from fastapi import Query

MAX_LIMIT = 100


def pagination(
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> tuple[int, int]:
    return limit, offset
