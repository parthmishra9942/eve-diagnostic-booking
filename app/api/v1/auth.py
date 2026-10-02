from fastapi import APIRouter, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import limiter
from app.schemas.user import LoginRequest, TokenResponse, UserCreate, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.auth_rate_limit)
async def signup(request: Request, data: UserCreate, session: DbSession):
    """Register a new (non-privileged) user."""
    return await AuthService(session).signup(data)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.auth_rate_limit)
async def login(request: Request, data: LoginRequest, session: DbSession):
    """Exchange email + password for a JWT bearer token."""
    return await AuthService(session).login(data.email, data.password)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser):
    """Profile of the authenticated user."""
    return user
