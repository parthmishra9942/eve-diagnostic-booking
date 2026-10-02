import logging
import random
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import compute_webhook_signature
from app.models import Booking, BookingStatus, Payment, PaymentStatus, User
from app.schemas.payment import SimulationMode, WebhookPayload

logger = logging.getLogger(__name__)


def simulate_gateway(mode: SimulationMode | None) -> PaymentStatus:
    """Mock payment gateway: forced outcome for testing, otherwise random (default 90% success)."""
    if mode is not None and mode != SimulationMode.RANDOM and not settings.allow_payment_simulation_override:
        raise BadRequestError("Forcing a payment outcome is disabled in this environment")
    if mode == SimulationMode.SUCCESS:
        return PaymentStatus.SUCCESS
    if mode == SimulationMode.FAILED:
        return PaymentStatus.FAILED
    return PaymentStatus.SUCCESS if random.random() < settings.payment_success_rate else PaymentStatus.FAILED


def build_signed_webhook(payment: Payment) -> WebhookPayload:
    """What the simulated payment provider would POST to our webhook endpoint."""
    event_id = f"evt_{payment.transaction_id}"
    signature = compute_webhook_signature(
        event_id=event_id,
        booking_id=payment.booking_id,
        transaction_id=payment.transaction_id,
        status=payment.status.value,
        amount=payment.amount,
    )
    return WebhookPayload(
        event_id=event_id,
        booking_id=payment.booking_id,
        transaction_id=payment.transaction_id,
        status=payment.status,
        amount=payment.amount,
        signature=signature,
    )


class PaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def initiate(self, user: User, booking_id: int, simulate: SimulationMode | None) -> Payment:
        """Runs the simulated gateway and records the Payment.

        The booking itself is NOT mutated here: like a real provider, the gateway reports the
        result asynchronously through the webhook, which is the single writer of booking state.
        """
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == booking_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if booking is None:
            raise NotFoundError("Booking not found")
        if booking.user_id != user.id:
            raise ForbiddenError("You do not have access to this booking")
        if booking.status != BookingStatus.PENDING:
            raise ConflictError(f"Payment cannot be initiated for a booking in {booking.status.value} state")
        already_paid = await self.session.scalar(
            select(func.count(Payment.id)).where(
                Payment.booking_id == booking.id, Payment.status == PaymentStatus.SUCCESS
            )
        )
        if already_paid:
            raise ConflictError("A successful payment already exists for this booking")

        payment = Payment(
            booking_id=booking.id,
            transaction_id=f"txn_{uuid.uuid4().hex[:24]}",
            amount=booking.amount,
            status=simulate_gateway(simulate),
        )
        self.session.add(payment)
        await self.session.commit()
        logger.info(
            "payment simulated",
            extra={"booking_id": booking.id, "transaction_id": payment.transaction_id, "payment_status": payment.status},
        )
        return payment
