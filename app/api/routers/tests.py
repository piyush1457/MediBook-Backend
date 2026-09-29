"""Diagnostic-test routes (public reads, admin writes)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import pagination
from app.api.deps import get_db, require_admin
from app.core.errors import ConflictError, NotFoundError
from app.models import Centre, CentreTest, DiagnosticTest, User
from app.schemas import (
    CentreOfferOut,
    DiagnosticTestCreate,
    DiagnosticTestDetailOut,
    DiagnosticTestOut,
    Page,
)

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("", response_model=Page[DiagnosticTestOut], summary="List diagnostic tests")
def list_tests(
    db: Session = Depends(get_db),
    search: str | None = Query(default=None),
    limit_offset: tuple[int, int] = Depends(pagination),
) -> Page[DiagnosticTestOut]:
    limit, offset = limit_offset
    stmt = select(DiagnosticTest)
    count_stmt = select(func.count()).select_from(DiagnosticTest)
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(func.lower(DiagnosticTest.name).like(like))
        count_stmt = count_stmt.where(func.lower(DiagnosticTest.name).like(like))
    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(stmt.order_by(DiagnosticTest.name).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return Page[DiagnosticTestOut](
        items=[DiagnosticTestOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{test_id}",
    response_model=DiagnosticTestDetailOut,
    summary="Test detail with offering centres",
)
def get_test(
    test_id: uuid.UUID, db: Session = Depends(get_db)
) -> DiagnosticTestDetailOut:
    test = db.get(DiagnosticTest, test_id)
    if test is None:
        raise NotFoundError("Test not found")
    rows = db.execute(
        select(CentreTest, Centre)
        .join(Centre, Centre.id == CentreTest.centre_id)
        .where(CentreTest.test_id == test.id)
        .order_by(Centre.name)
    ).all()
    out = DiagnosticTestDetailOut.model_validate(test)
    out.centres = [
        CentreOfferOut(centre_id=c.id, centre_name=c.name, city=c.city, price=ct.price)
        for ct, c in rows
    ]
    return out


@router.post(
    "",
    response_model=DiagnosticTestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create test (admin)",
)
def create_test(
    body: DiagnosticTestCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> DiagnosticTest:
    test = DiagnosticTest(name=body.name.strip(), description=body.description.strip())
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("A test with this name already exists")
    db.refresh(test)
    return test
