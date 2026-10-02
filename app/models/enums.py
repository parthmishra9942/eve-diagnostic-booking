try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Python 3.10 compatibility fallback for StrEnum."""
        pass


class UserRole(StrEnum):
    USER = "USER"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


class BookingStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class WebhookOutcome(StrEnum):
    APPLIED = "APPLIED"  # the event changed booking state
    IGNORED = "IGNORED"  # valid event, but the state machine guard rejected the transition
