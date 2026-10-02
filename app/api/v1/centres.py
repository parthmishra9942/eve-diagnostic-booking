import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, StaffUser
from app.core.cache import cache
from app.schemas.catalog import (
    CentreCreate,
    CentreRead,
    CentreTestCreate,
    CentreTestRead,
    CentreTestUpdate,
)
from app.schemas.common import Page
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/centres", tags=["Diagnostic Centres"])

CACHE_NAMESPACE = "centres"


@router.post("", response_model=CentreRead, status_code=status.HTTP_201_CREATED)
async def create_centre(data: CentreCreate, session: DbSession, _staff: StaffUser):
    """Create a diagnostic centre (staff/admin only)."""
    centre = await CatalogService(session).create_centre(data)
    await cache.bump_version(CACHE_NAMESPACE)
    return centre


@router.get("", response_model=Page[CentreRead])
async def list_centres(
    session: DbSession,
    name: Annotated[str | None, Query(max_length=150, description="Case-insensitive name contains")] = None,
    location: Annotated[str | None, Query(max_length=200, description="Case-insensitive location contains")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List active centres with search + pagination. Responses are cached in Redis (fail-open)."""
    params = {"name": name, "location": location, "limit": limit, "offset": offset}
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:32]
    version = await cache.get_version(CACHE_NAMESPACE)
    key = f"centres:list:v{version}:{digest}"

    cached = await cache.get_json(key)
    if cached is not None:
        return cached

    items, total = await CatalogService(session).list_centres(name=name, location=location, limit=limit, offset=offset)
    page = Page[CentreRead](
        items=[CentreRead.model_validate(c) for c in items], total=total, limit=limit, offset=offset
    )
    await cache.set_json(key, page.model_dump(mode="json"))
    return page


@router.get("/{centre_id}", response_model=CentreRead)
async def get_centre(centre_id: int, session: DbSession):
    return await CatalogService(session).get_centre(centre_id)


@router.get("/{centre_id}/tests", response_model=list[CentreTestRead])
async def list_centre_tests(centre_id: int, session: DbSession):
    """Tests offered by a centre, with price and turnaround time."""
    return await CatalogService(session).list_centre_tests(centre_id)


@router.post("/{centre_id}/tests", response_model=CentreTestRead, status_code=status.HTTP_201_CREATED)
async def link_test(centre_id: int, data: CentreTestCreate, session: DbSession, _staff: StaffUser):
    """Offer a diagnostic test at a centre with a price (staff/admin only)."""
    return await CatalogService(session).link_test(centre_id, data)


@router.put("/{centre_id}/tests/{test_id}", response_model=CentreTestRead)
async def update_centre_test(
    centre_id: int, test_id: int, data: CentreTestUpdate, session: DbSession, _staff: StaffUser
):
    """Change the price / turnaround of a test at a centre. Existing bookings keep their locked price."""
    return await CatalogService(session).update_link(centre_id, test_id, data)
