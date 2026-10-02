from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BookingStatus, PaymentStatus, WebhookOutcome
from app.schemas.common import MoneyIn, MoneyOut


class SimulationMode(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RANDOM = "random"


class PaymentCreate(BaseModel):
    booking_id: int


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    transaction_id: str
    amount: MoneyOut
    status: PaymentStatus
    created_at: datetime


class WebhookPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    booking_id: int
    transaction_id: str = Field(min_length=1, max_length=64)
    status: PaymentStatus
    amount: MoneyIn
    signature: str = Field(min_length=1)


class WebhookResponse(BaseModel):
    status: str  # "processed" | "already_processed"
    event_id: str
    booking_id: int
    booking_status: BookingStatus
    outcome: WebhookOutcome | None = None
