import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import AppError, BadRequestError, NotFoundError, UnauthorizedError
from app.core.security import verify_webhook_signature
from app.models import Booking, BookingStatus, Payment, PaymentStatus, WebhookEvent, WebhookOutcome
from app.models.types import utcnow
from app.schemas.payment import WebhookPayload, WebhookResponse

logger = logging.getLogger(__name__)


class WebhookService:
    """Idempotent processor for payment-provider webhooks.

    Guarantees (see README "Idempotency & Concurrency Design"):
      1. UNIQUE(webhook_events.event_id) is the idempotency key / last line of defence.
      2. SELECT ... FOR UPDATE on the Booking row serialises concurrent deliveries, so a
         duplicate re-checks the ledger only after the first delivery has committed.
      3. A state-machine guard makes transitions monotonic (never regress or re-apply).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def process(self, payload: WebhookPayload) -> WebhookResponse:
        self._verify_signature(payload)

        # Fast path: already handled -> no locks, no business logic.
        existing = await self._find_event(payload.event_id)
        if existing is not None:
            return await self._already_processed(existing)

        try:
            return await self._apply(payload)
        except IntegrityError:
            # A concurrent delivery committed the same event_id between our check and insert
            # (the unique constraint caught it). Treat as a duplicate.
            await self.session.rollback()
            existing = await self._find_event(payload.event_id)
            if existing is None:
                raise
            return await self._already_processed(existing)

    # ------------------------------------------------------------------
    def _verify_signature(self, payload: WebhookPayload) -> None:
        valid = verify_webhook_signature(
            signature=payload.signature,
            event_id=payload.event_id,
            booking_id=payload.booking_id,
            transaction_id=payload.transaction_id,
            status=payload.status.value,
            amount=payload.amount,
        )
        if not valid:
            logger.warning("webhook rejected: bad signature", extra={"event_id": payload.event_id})
            raise UnauthorizedError("Invalid webhook signature")

    async def _find_event(self, event_id: str) -> WebhookEvent | None:
        return await self.session.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.event_id == event_id)
            .execution_options(populate_existing=True)
        )

    async def _already_processed(self, event: WebhookEvent) -> WebhookResponse:
        booking = await self.session.get(Booking, event.booking_id, populate_existing=True)
        assert booking is not None
        logger.info("webhook duplicate ignored", extra={"event_id": event.event_id, "booking_id": booking.id})
        return WebhookResponse(
            status="already_processed",
            event_id=event.event_id,
            booking_id=booking.id,
            booking_status=booking.status,
            outcome=event.outcome,
        )

    async def _apply(self, payload: WebhookPayload) -> WebhookResponse:
        # (2) Pessimistic row lock: concurrent deliveries for this booking queue up here.
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == payload.booking_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if booking is None:
            raise NotFoundError("Booking not found")

        # Re-check after acquiring the lock: if a concurrent twin won, it has committed by now.
        existing = await self._find_event(payload.event_id)
        if existing is not None:
            response = await self._already_processed(existing)  # read before rollback expires ORM state
            await self.session.rollback()  # release the row lock
            return response

        payment = await self.session.scalar(
            select(Payment)
            .where(Payment.transaction_id == payload.transaction_id, Payment.booking_id == booking.id)
            .execution_options(populate_existing=True)
        )
        if payment is None:
            raise NotFoundError("No payment found for this booking and transaction_id")
        if payload.amount != booking.amount or payload.amount != payment.amount:
            raise BadRequestError("Webhook amount does not match the booking amount")

        outcome = self._transition(booking, payload.status)

        # (1) Record the event in the same transaction as the state change. If the unique
        # constraint fires, everything rolls back and the caller reports a duplicate.
        self.session.add(
            WebhookEvent(
                event_id=payload.event_id,
                booking_id=booking.id,
                transaction_id=payload.transaction_id,
                status=payload.status,
                amount=payload.amount,
                outcome=outcome,
                payload=payload.model_dump(mode="json", exclude={"signature"}),
            )
        )
        if outcome == WebhookOutcome.APPLIED:
            payment.status = payload.status
            payment.updated_at = utcnow()
        await self.session.commit()

        logger.info(
            "webhook processed",
            extra={
                "event_id": payload.event_id,
                "booking_id": booking.id,
                "booking_status": booking.status,
                "outcome": outcome,
            },
        )
        return WebhookResponse(
            status="processed",
            event_id=payload.event_id,
            booking_id=booking.id,
            booking_status=booking.status,
            outcome=outcome,
        )

    @staticmethod
    def _transition(booking: Booking, status: PaymentStatus) -> WebhookOutcome:
        """(3) State-machine guard: only PENDING bookings can be moved by a payment event.

        CONFIRMED never regresses to FAILED nor is re-confirmed; FAILED/CANCELLED are terminal.
        """
        if booking.status != BookingStatus.PENDING:
            logger.warning(
                "webhook ignored by state guard",
                extra={"booking_id": booking.id, "booking_status": booking.status, "event_status": status},
            )
            return WebhookOutcome.IGNORED
        booking.status = BookingStatus.CONFIRMED if status == PaymentStatus.SUCCESS else BookingStatus.FAILED
        booking.updated_at = utcnow()
        return WebhookOutcome.APPLIED


async def dispatch_webhook(payload: WebhookPayload) -> None:
    """Background task simulating the provider's asynchronous webhook delivery.

    Retries transient failures with exponential backoff. Retrying is safe because
    processing is idempotent. Business-rule rejections (AppError) are not retried.
    """
    if settings.webhook_dispatch_delay_seconds > 0:
        await asyncio.sleep(settings.webhook_dispatch_delay_seconds)
    for attempt in range(1, settings.webhook_max_retries + 1):
        try:
            async with SessionLocal() as session:
                await WebhookService(session).process(payload)
            return
        except AppError as exc:
            logger.error("webhook dispatch rejected", extra={"event_id": payload.event_id, "reason": exc.message})
            return
        except Exception:  # noqa: BLE001 - transient (DB down, deadlock, ...) -> retry
            logger.exception(
                "webhook dispatch failed", extra={"event_id": payload.event_id, "attempt": attempt}
            )
            if attempt < settings.webhook_max_retries:
                await asyncio.sleep(0.1 * 2**attempt)
    logger.error("webhook dispatch gave up", extra={"event_id": payload.event_id})
