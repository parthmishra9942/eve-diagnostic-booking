from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MoneyIn, MoneyOut


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    location: str = Field(min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class CentreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str
    contact: str | None
    is_active: bool
    created_at: datetime


class TestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)


class TestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    category: str | None


class CentreTestCreate(BaseModel):
    test_id: int
    price: MoneyIn
    turnaround_hours: int = Field(default=24, gt=0, le=24 * 60)


class CentreTestUpdate(BaseModel):
    price: MoneyIn | None = None
    turnaround_hours: int | None = Field(default=None, gt=0, le=24 * 60)


class CentreTestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    centre_id: int
    test: TestRead
    price: MoneyOut
    turnaround_hours: int
