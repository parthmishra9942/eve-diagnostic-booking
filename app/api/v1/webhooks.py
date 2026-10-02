from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.payment import WebhookPayload, WebhookResponse
from app.services.webhook_service import WebhookService

router = APIRouter(prefix="/payments", tags=["Webhooks"])


@router.post("/webhook", response_model=WebhookResponse)
async def payment_webhook(payload: WebhookPayload, session: DbSession):
    """Idempotent payment-provider callback, authenticated by HMAC signature.

    Replays of the same `event_id` return HTTP 200 with `status: "already_processed"`.
    """
    return await WebhookService(session).process(payload)
