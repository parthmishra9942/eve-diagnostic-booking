from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import limiter
from app.schemas.payment import PaymentCreate, PaymentRead, SimulationMode
from app.services.payment_service import PaymentService, build_signed_webhook
from app.services.webhook_service import dispatch_webhook

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.payment_rate_limit)
async def create_payment(
    request: Request,
    data: PaymentCreate,
    background_tasks: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    simulate: Annotated[
        SimulationMode | None,
        Query(description="Testing aid: force `success` or `failed`. Default `random` (90% success)."),
    ] = None,
):
    """Simulated payment. The gateway result is delivered asynchronously via the signed webhook,
    which then moves the booking to CONFIRMED / FAILED."""
    payment = await PaymentService(session).initiate(user, data.booking_id, simulate)
    if settings.webhook_auto_dispatch:
        background_tasks.add_task(dispatch_webhook, build_signed_webhook(payment))
    return payment
