from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.models import BookingStatus
from app.schemas.booking import BookingCreate, BookingRead
from app.schemas.common import Page
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
async def create_booking(data: BookingCreate, session: DbSession, user: CurrentUser):
    """Book a test at a centre. The current price is locked in; the booking starts as PENDING."""
    return await BookingService(session).create(user, data)


@router.get("", response_model=Page[BookingRead])
async def list_my_bookings(
    session: DbSession,
    user: CurrentUser,
    status_filter: Annotated[BookingStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Only the authenticated user's own bookings."""
    items, total = await BookingService(session).list_for_user(
        user, status=status_filter, limit=limit, offset=offset
    )
    return Page[BookingRead](
        items=[BookingRead.model_validate(b) for b in items], total=total, limit=limit, offset=offset
    )


@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking(booking_id: int, session: DbSession, user: CurrentUser):
    """404 if the booking doesn't exist, 403 if it belongs to someone else."""
    return await BookingService(session).get_owned(booking_id, user)


@router.post("/{booking_id}/cancel", response_model=BookingRead)
async def cancel_booking(booking_id: int, session: DbSession, user: CurrentUser):
    """Cancel a PENDING or CONFIRMED booking (409 for any other state)."""
    return await BookingService(session).cancel(booking_id, user)
