import asyncio

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.user import TokenResponse, UserCreate


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self, *, email: str, full_name: str, password: str, role: UserRole = UserRole.USER
    ) -> User:
        email = email.strip().lower()
        existing = await self.session.scalar(select(User.id).where(User.email == email))
        if existing is not None:
            raise ConflictError("A user with this email already exists")
        # bcrypt is CPU-bound; keep it off the event loop.
        hashed = await asyncio.to_thread(hash_password, password)
        user = User(email=email, full_name=full_name, hashed_password=hashed, role=role)
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError:  # lost a race against a concurrent signup
            await self.session.rollback()
            raise ConflictError("A user with this email already exists") from None
        return user

    async def signup(self, data: UserCreate) -> User:
        # Public signup can only ever create regular users (no privilege escalation).
        return await self.create_user(
            email=data.email, full_name=data.full_name, password=data.password, role=UserRole.USER
        )

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.session.scalar(select(User).where(User.email == email.strip().lower()))
        valid = user is not None and await asyncio.to_thread(verify_password, password, user.hashed_password)
        if not valid or user is None or not user.is_active:
            raise UnauthorizedError("Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
        token, expires_in = create_access_token(user.id, user.role.value)
        return TokenResponse(access_token=token, expires_in=expires_in)
