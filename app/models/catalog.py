from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import UTCDateTime, utcnow


class Centre(Base):
    __tablename__ = "centres"
    __table_args__ = (UniqueConstraint("name", "location", name="uq_centres_name_location"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    location: Mapped[str] = mapped_column(String(200), index=True)
    contact: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CentreTest(Base):
    """Association object: which centre offers which test, at what price / turnaround."""

    __tablename__ = "centre_tests"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("turnaround_hours > 0", name="turnaround_positive"),
    )

    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id", ondelete="CASCADE"), primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id", ondelete="CASCADE"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    turnaround_hours: Mapped[int] = mapped_column(default=24)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    test: Mapped[DiagnosticTest] = relationship(lazy="joined", innerjoin=True)
