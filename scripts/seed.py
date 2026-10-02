"""Database seeding script for EVE Diagnostic Booking Service.

Populates the database with realistic healthcare diagnostic centres, tests,
pricing, demo users (Admin, Staff, Patient), and sample bookings.

Idempotent: Safe to run repeatedly; existing records are detected and skipped.

Usage:
    python -m scripts.seed
    # OR
    python scripts/seed.py
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.security import compute_webhook_signature, hash_password
from app.models import (
    Booking,
    BookingStatus,
    Centre,
    CentreTest,
    DiagnosticTest,
    Payment,
    PaymentStatus,
    User,
    UserRole,
    WebhookEvent,
    WebhookOutcome,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed")


async def seed() -> None:
    logger.info("Starting database seeding...")

    async with SessionLocal() as session:
        # 1. Users
        users_data = [
            ("admin@example.com", "System Administrator", "Admin12345", UserRole.ADMIN),
            ("staff@example.com", "Lab Supervisor", "Staff12345", UserRole.STAFF),
            ("patient@example.com", "Rahul Sharma", "Patient12345", UserRole.USER),
            ("patient2@example.com", "Priya Verma", "Patient12345", UserRole.USER),
        ]
        user_map: dict[str, User] = {}
        for email, name, pwd, role in users_data:
            existing = await session.scalar(select(User).where(User.email == email))
            if existing:
                user_map[email] = existing
                logger.info(f"User already exists: {email} ({role})")
            else:
                user = User(
                    email=email,
                    full_name=name,
                    hashed_password=hash_password(pwd),
                    role=role,
                )
                session.add(user)
                await session.flush()
                user_map[email] = user
                logger.info(f"Created user: {email} ({role})")

        # 2. Diagnostic Centres
        centres_data = [
            (
                "Apollo Diagnostics - Indiranagar",
                "100 Feet Road, Indiranagar, Bengaluru, Karnataka",
                "+91-80-25251122",
            ),
            (
                "Dr. Lal PathLabs - Green Park",
                "Main Market, Green Park, New Delhi",
                "+91-11-49885050",
            ),
            (
                "SRL Diagnostics - Andheri West",
                "SV Road, Near Station, Andheri West, Mumbai, Maharashtra",
                "+91-22-67891234",
            ),
            (
                "Max Healthcare Diagnostics - Saket",
                "Press Enclave Road, Saket, New Delhi",
                "+91-11-26515050",
            ),
        ]
        centre_map: dict[str, Centre] = {}
        for name, location, contact in centres_data:
            existing = await session.scalar(select(Centre).where(Centre.name == name))
            if existing:
                centre_map[name] = existing
                logger.info(f"Centre already exists: {name}")
            else:
                c = Centre(name=name, location=location, contact=contact, is_active=True)
                session.add(c)
                await session.flush()
                centre_map[name] = c
                logger.info(f"Created centre: {name}")

        # 3. Diagnostic Tests
        tests_data = [
            (
                "Complete Blood Count (CBC)",
                "Evaluates overall health and detects a wide range of disorders including anemia and leukemia.",
                "Hematology",
            ),
            (
                "Lipid Profile Panel",
                "Measures cholesterol and triglyceride levels to assess cardiovascular disease risk.",
                "Biochemistry",
            ),
            (
                "HbA1c (Glycated Hemoglobin)",
                "Reflects average blood sugar levels over the past 2 to 3 months for diabetes monitoring.",
                "Diabetes",
            ),
            (
                "Thyroid Profile (T3, T4, TSH)",
                "Evaluates thyroid gland function and metabolic health.",
                "Endocrinology",
            ),
            (
                "Chest X-Ray PA View",
                "Digital radiographic imaging of the chest, lungs, and heart.",
                "Radiology",
            ),
            (
                "MRI Brain (Plain)",
                "High-resolution magnetic resonance imaging of brain tissue and neural structures.",
                "Radiology & Imaging",
            ),
        ]
        test_map: dict[str, DiagnosticTest] = {}
        for name, desc, cat in tests_data:
            existing = await session.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
            if existing:
                test_map[name] = existing
                logger.info(f"Test already exists: {name}")
            else:
                t = DiagnosticTest(name=name, description=desc, category=cat)
                session.add(t)
                await session.flush()
                test_map[name] = t
                logger.info(f"Created test: {name}")

        # 4. Link Tests to Centres with Pricing (CentreTest)
        # Pricing matrix: (Centre Name, Test Name, Price, Turnaround Hours)
        pricing_data = [
            ("Apollo Diagnostics - Indiranagar", "Complete Blood Count (CBC)", Decimal("350.00"), 12),
            ("Apollo Diagnostics - Indiranagar", "Lipid Profile Panel", Decimal("750.00"), 24),
            ("Apollo Diagnostics - Indiranagar", "HbA1c (Glycated Hemoglobin)", Decimal("500.00"), 12),
            ("Apollo Diagnostics - Indiranagar", "Thyroid Profile (T3, T4, TSH)", Decimal("650.00"), 24),
            ("Apollo Diagnostics - Indiranagar", "Chest X-Ray PA View", Decimal("450.00"), 6),
            ("Dr. Lal PathLabs - Green Park", "Complete Blood Count (CBC)", Decimal("320.00"), 8),
            ("Dr. Lal PathLabs - Green Park", "Lipid Profile Panel", Decimal("700.00"), 16),
            ("Dr. Lal PathLabs - Green Park", "HbA1c (Glycated Hemoglobin)", Decimal("480.00"), 10),
            ("Dr. Lal PathLabs - Green Park", "Thyroid Profile (T3, T4, TSH)", Decimal("600.00"), 18),
            ("SRL Diagnostics - Andheri West", "Complete Blood Count (CBC)", Decimal("360.00"), 12),
            ("SRL Diagnostics - Andheri West", "Lipid Profile Panel", Decimal("780.00"), 24),
            ("SRL Diagnostics - Andheri West", "MRI Brain (Plain)", Decimal("5500.00"), 24),
            ("Max Healthcare Diagnostics - Saket", "MRI Brain (Plain)", Decimal("6200.00"), 18),
            ("Max Healthcare Diagnostics - Saket", "Chest X-Ray PA View", Decimal("500.00"), 4),
            ("Max Healthcare Diagnostics - Saket", "Lipid Profile Panel", Decimal("850.00"), 12),
        ]
        for cname, tname, price, tat in pricing_data:
            centre = centre_map[cname]
            test = test_map[tname]
            link = await session.scalar(
                select(CentreTest).where(
                    CentreTest.centre_id == centre.id,
                    CentreTest.test_id == test.id,
                )
            )
            if not link:
                session.add(
                    CentreTest(
                        centre_id=centre.id,
                        test_id=test.id,
                        price=price,
                        turnaround_hours=tat,
                        is_available=True,
                    )
                )
                logger.info(f"Linked {cname} -> {tname} (INR {price})")

        # 5. Sample Bookings & Payment Flow Demonstration
        patient = user_map["patient@example.com"]
        apollo = centre_map["Apollo Diagnostics - Indiranagar"]
        cbc_test = test_map["Complete Blood Count (CBC)"]
        lipid_test = test_map["Lipid Profile Panel"]

        # Sample Booking 1: CONFIRMED Booking with simulated payment and webhook event
        existing_b1 = await session.scalar(
            select(Booking).where(Booking.user_id == patient.id, Booking.status == BookingStatus.CONFIRMED)
        )
        if not existing_b1:
            b1 = Booking(
                user_id=patient.id,
                centre_id=apollo.id,
                test_id=cbc_test.id,
                appointment_datetime=datetime.now(UTC) + timedelta(days=2),
                amount=Decimal("350.00"),
                status=BookingStatus.CONFIRMED,
            )
            session.add(b1)
            await session.flush()

            txn_id = f"txn_demo_{b1.id}_seed"
            p1 = Payment(
                booking_id=b1.id,
                transaction_id=txn_id,
                amount=Decimal("350.00"),
                status=PaymentStatus.SUCCESS,
            )
            session.add(p1)

            event_id = f"evt_demo_seed_{b1.id}"
            ev1 = WebhookEvent(
                event_id=event_id,
                booking_id=b1.id,
                transaction_id=txn_id,
                status=PaymentStatus.SUCCESS,
                amount=Decimal("350.00"),
                outcome=WebhookOutcome.APPLIED,
                payload={
                    "event_id": event_id,
                    "booking_id": b1.id,
                    "transaction_id": txn_id,
                    "status": "SUCCESS",
                    "amount": 350.00,
                },
            )
            session.add(ev1)
            logger.info(f"Created sample CONFIRMED booking #{b1.id} with Payment and WebhookEvent")

        # Sample Booking 2: PENDING Booking ready for immediate payment / webhook testing
        existing_b2 = await session.scalar(
            select(Booking).where(Booking.user_id == patient.id, Booking.status == BookingStatus.PENDING)
        )
        if not existing_b2:
            b2 = Booking(
                user_id=patient.id,
                centre_id=apollo.id,
                test_id=lipid_test.id,
                appointment_datetime=datetime.now(UTC) + timedelta(days=3),
                amount=Decimal("750.00"),
                status=BookingStatus.PENDING,
            )
            session.add(b2)
            await session.flush()
            logger.info(f"Created sample PENDING booking #{b2.id} ready for testing")

        await session.commit()

    logger.info("✅ Database seeding successfully completed!")
    print("\n" + "=" * 65)
    print("🎉 EVE DIAGNOSTICS SEED COMPLETE — READY FOR TESTING")
    print("=" * 65)
    print("Demo Credentials:")
    print("  • Admin:   admin@example.com   / Admin12345")
    print("  • Staff:   staff@example.com   / Staff12345")
    print("  • Patient: patient@example.com / Patient12345")
    print("Interactive Swagger UI: http://localhost:8000/docs")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
