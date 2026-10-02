from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, StaffUser
from app.schemas.catalog import TestCreate, TestRead
from app.schemas.common import Page
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/tests", tags=["Diagnostic Tests"])


@router.post("", response_model=TestRead, status_code=status.HTTP_201_CREATED)
async def create_test(data: TestCreate, session: DbSession, _staff: StaffUser):
    """Add a diagnostic test to the global catalogue (staff/admin only)."""
    return await CatalogService(session).create_test(data)


@router.get("", response_model=Page[TestRead])
async def list_tests(
    session: DbSession,
    category: Annotated[str | None, Query(max_length=100)] = None,
    name: Annotated[str | None, Query(max_length=150)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = await CatalogService(session).list_tests(category=category, name=name, limit=limit, offset=offset)
    return Page[TestRead](items=[TestRead.model_validate(t) for t in items], total=total, limit=limit, offset=offset)


@router.get("/{test_id}", response_model=TestRead)
async def get_test(test_id: int, session: DbSession):
    return await CatalogService(session).get_test(test_id)
