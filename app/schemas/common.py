from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, Field, PlainSerializer

T = TypeVar("T")

# Money is Decimal internally (no float rounding), rendered as a JSON number.
_to_float = PlainSerializer(lambda v: float(v), return_type=float, when_used="json")
MoneyOut = Annotated[Decimal, _to_float]
MoneyIn = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2), _to_float]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
