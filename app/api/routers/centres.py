"""Centre routes (public reads, admin writes)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import pagination
from app.api.deps import get_db, require_admin
from app.core.errors import ConflictError, NotFoundError
from app.models import Centre, CentreTest, DiagnosticTest, User
from app.schemas import (
    AttachTestIn,
    CentreCreate,
    CentreDetailOut,
    CentreOut,
    CentreTestOut,
    Page,
)

router = APIRouter(prefix="/centres", tags=["centres"])


@router.get(
    "", response_model=Page[CentreOut], summary="List centres (filter by city/search)"
)
def list_centres(
    db: Session = Depends(get_db),
    city: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit_offset: tuple[int, int] = Depends(pagination),
) -> Page[CentreOut]:
    limit, offset = limit_offset
    stmt = select(Centre)
    count_stmt = select(func.count()).select_from(Centre)
    if city:
        stmt = stmt.where(func.lower(Centre.city) == city.strip().lower())
        count_stmt = count_stmt.where(func.lower(Centre.city) == city.strip().lower())
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Centre.name).like(like), func.lower(Centre.city).like(like))
        )
        count_stmt = count_stmt.where(
            or_(func.lower(Centre.name).like(like), func.lower(Centre.city).like(like))
        )
    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(stmt.order_by(Centre.name).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return Page[CentreOut](
        items=[CentreOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{centre_id}",
    response_model=CentreDetailOut,
    summary="Centre detail with tests & prices",
)
def get_centre(centre_id: uuid.UUID, db: Session = Depends(get_db)) -> CentreDetailOut:
    centre = db.get(Centre, centre_id)
    if centre is None:
        raise NotFoundError("Centre not found")
    rows = db.execute(
        select(CentreTest, DiagnosticTest)
        .join(DiagnosticTest, DiagnosticTest.id == CentreTest.test_id)
        .where(CentreTest.centre_id == centre.id)
        .order_by(DiagnosticTest.name)
    ).all()
    out = CentreDetailOut.model_validate(centre)
    out.tests = [
        CentreTestOut(test_id=t.id, test_name=t.name, price=ct.price) for ct, t in rows
    ]
    return out


@router.post(
    "",
    response_model=CentreOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create centre (admin)",
)
def create_centre(
    body: CentreCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Centre:
    centre = Centre(
        name=body.name.strip(), city=body.city.strip(), address=body.address.strip()
    )
    db.add(centre)
    db.commit()
    db.refresh(centre)
    return centre


@router.post(
    "/{centre_id}/tests",
    status_code=status.HTTP_201_CREATED,
    summary="Offer a test at a centre (admin)",
)
def attach_test(
    centre_id: uuid.UUID,
    body: AttachTestIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    from sqlalchemy.exc import IntegrityError

    centre = db.get(Centre, centre_id)
    if centre is None:
        raise NotFoundError("Centre not found")
    test = db.get(DiagnosticTest, body.test_id)
    if test is None:
        raise NotFoundError("Test not found")
    link = CentreTest(centre_id=centre.id, test_id=test.id, price=body.price)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This centre already offers this test")
    return {
        "centre_id": str(centre.id),
        "test_id": str(test.id),
        "price": str(body.price),
    }
