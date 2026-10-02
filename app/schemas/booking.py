from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import BookingStatus
from app.schemas.common import MoneyOut


class BookingCreate(BaseModel):
    centre_id: int
    test_id: int
    appointment_datetime: datetime

    @field_validator("appointment_datetime")
    @classmethod
    def must_be_in_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:  # naive values are interpreted as UTC
            value = value.replace(tzinfo=UTC)
        if value <= datetime.now(UTC):
            raise ValueError("must be strictly in the future")
        return value.astimezone(UTC)


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    centre_id: int
    test_id: int
    appointment_datetime: datetime
    amount: MoneyOut
    status: BookingStatus
    created_at: datetime
    updated_at: datetime
