from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_column
from app.models.enums import PaymentStatus, WebhookOutcome
from app.models.types import UTCDateTime, utcnow


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), index=True)
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(enum_column(PaymentStatus, "payment_status"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class WebhookEvent(Base):
    """Ledger of processed webhook events. The unique event_id is the idempotency key."""

    __tablename__ = "webhook_events"
    __table_args__ = (Index("ix_webhook_events_booking_id", "booking_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    transaction_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[PaymentStatus] = mapped_column(enum_column(PaymentStatus, "webhook_status"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    outcome: Mapped[WebhookOutcome] = mapped_column(enum_column(WebhookOutcome, "webhook_outcome"))
    payload: Mapped[dict] = mapped_column(JSON)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
