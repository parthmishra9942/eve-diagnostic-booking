import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models import Booking, BookingStatus, Centre, CentreTest, DiagnosticTest, User
from app.models.types import utcnow
from app.schemas.booking import BookingCreate

logger = logging.getLogger(__name__)

CANCELLABLE_STATES = {BookingStatus.PENDING, BookingStatus.CONFIRMED}


class BookingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user: User, data: BookingCreate) -> Booking:
        centre = await self.session.get(Centre, data.centre_id)
        if centre is None:
            raise NotFoundError("Diagnostic centre not found")
        if not centre.is_active:
            raise BadRequestError("This diagnostic centre is not currently accepting bookings")
        if await self.session.get(DiagnosticTest, data.test_id) is None:
            raise NotFoundError("Diagnostic test not found")
        offering = await self.session.get(CentreTest, (data.centre_id, data.test_id))
        if offering is None:
            raise BadRequestError("The selected diagnostic centre does not offer the selected test")

        booking = Booking(
            user_id=user.id,
            centre_id=data.centre_id,
            test_id=data.test_id,
            appointment_datetime=data.appointment_datetime,
            amount=offering.price,  # price is locked in at booking time
            status=BookingStatus.PENDING,
        )
        self.session.add(booking)
        await self.session.commit()
        logger.info("booking created", extra={"booking_id": booking.id, "user_id": user.id})
        return booking

    async def list_for_user(
        self, user: User, *, status: BookingStatus | None, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        conditions = [Booking.user_id == user.id]
        if status is not None:
            conditions.append(Booking.status == status)
        total = await self.session.scalar(select(func.count()).select_from(Booking).where(*conditions)) or 0
        rows = await self.session.scalars(
            select(Booking).where(*conditions).order_by(Booking.id.desc()).limit(limit).offset(offset)
        )
        return list(rows), total

    async def get_owned(self, booking_id: int, user: User) -> Booking:
        booking = await self.session.get(Booking, booking_id)
        return self._assert_owner(booking, user)

    async def cancel(self, booking_id: int, user: User) -> Booking:
        # Row lock serialises cancellation against concurrent payment webhooks.
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == booking_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        booking = self._assert_owner(booking, user)
        if booking.status not in CANCELLABLE_STATES:
            raise ConflictError(f"A booking in {booking.status.value} state cannot be cancelled")
        booking.status = BookingStatus.CANCELLED
        booking.updated_at = utcnow()
        await self.session.commit()
        logger.info("booking cancelled", extra={"booking_id": booking.id, "user_id": user.id})
        return booking

    @staticmethod
    def _assert_owner(booking: Booking | None, user: User) -> Booking:
        if booking is None:
            raise NotFoundError("Booking not found")
        if booking.user_id != user.id:
            raise ForbiddenError("You do not have access to this booking")
        return booking
