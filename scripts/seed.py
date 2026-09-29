"""Seed centres, tests, prices + one admin user (credentials from env).

Run:  python scripts/seed.py
Idempotent: skips rows that already exist.
"""

from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import Centre, CentreTest, DiagnosticTest, User

CENTRES = [
    {
        "name": "EVE Diagnostics - Indiranagar",
        "city": "Bengaluru",
        "address": "100 Feet Rd, Indiranagar",
    },
    {
        "name": "EVE Diagnostics - Andheri",
        "city": "Mumbai",
        "address": "Link Rd, Andheri West",
    },
    {
        "name": "EVE Diagnostics - Connaught Place",
        "city": "Delhi",
        "address": "G Block, Connaught Place",
    },
]

TESTS = [
    {"name": "CBC", "description": "Complete blood count"},
    {"name": "HbA1c", "description": "Glycated haemoglobin"},
    {"name": "Lipid Profile", "description": "Cholesterol panel"},
    {"name": "Thyroid TSH", "description": "Thyroid stimulating hormone"},
]

# (centre_index, test_name) -> price INR
PRICES = {
    (0, "CBC"): Decimal("299.00"),
    (0, "HbA1c"): Decimal("499.00"),
    (0, "Lipid Profile"): Decimal("799.00"),
    (1, "CBC"): Decimal("349.00"),
    (1, "Thyroid TSH"): Decimal("450.00"),
    (2, "CBC"): Decimal("320.00"),
    (2, "HbA1c"): Decimal("520.00"),
    (2, "Thyroid TSH"): Decimal("475.00"),
}


def main() -> None:
    engine = create_engine(settings.DATABASE_URL, future=True)
    with Session(engine) as db:
        email = settings.ADMIN_EMAIL.strip().lower()
        admin = db.execute(
            select(User).where(func.lower(User.email) == email)
        ).scalar_one_or_none()
        if admin is None:
            db.add(
                User(
                    email=email,
                    hashed_password=hash_password(settings.ADMIN_PASSWORD),
                    full_name=settings.ADMIN_NAME,
                    is_admin=True,
                )
            )
            print(f"created admin {email}")
        else:
            print(f"admin exists {email}")

        centres: list[Centre] = []
        for c in CENTRES:
            row = db.execute(
                select(Centre).where(Centre.name == c["name"])
            ).scalar_one_or_none()
            if row is None:
                row = Centre(**c)
                db.add(row)
                db.flush()
            centres.append(row)

        tests: dict[str, DiagnosticTest] = {}
        for t in TESTS:
            row = db.execute(
                select(DiagnosticTest).where(DiagnosticTest.name == t["name"])
            ).scalar_one_or_none()
            if row is None:
                row = DiagnosticTest(**t)
                db.add(row)
                db.flush()
            tests[row.name] = row

        for (ci, tname), price in PRICES.items():
            link = db.execute(
                select(CentreTest).where(
                    CentreTest.centre_id == centres[ci].id,
                    CentreTest.test_id == tests[tname].id,
                )
            ).scalar_one_or_none()
            if link is None:
                db.add(
                    CentreTest(
                        centre_id=centres[ci].id, test_id=tests[tname].id, price=price
                    )
                )

        db.commit()
        print("seed complete")


if __name__ == "__main__":
    main()
