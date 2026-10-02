from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Centre, CentreTest, DiagnosticTest
from app.schemas.catalog import CentreCreate, CentreTestCreate, CentreTestUpdate, TestCreate


def _like(value: str) -> str:
    escaped = value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class CatalogService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---- centres -------------------------------------------------------
    async def create_centre(self, data: CentreCreate) -> Centre:
        centre = Centre(**data.model_dump())
        self.session.add(centre)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError("A centre with this name already exists at this location") from None
        return centre

    async def list_centres(
        self, *, name: str | None, location: str | None, limit: int, offset: int
    ) -> tuple[list[Centre], int]:
        conditions = [Centre.is_active.is_(True)]
        if name:
            conditions.append(Centre.name.ilike(_like(name), escape="\\"))
        if location:
            conditions.append(Centre.location.ilike(_like(location), escape="\\"))
        total = await self.session.scalar(select(func.count()).select_from(Centre).where(*conditions)) or 0
        rows = await self.session.scalars(
            select(Centre).where(*conditions).order_by(Centre.name, Centre.id).limit(limit).offset(offset)
        )
        return list(rows), total

    async def get_centre(self, centre_id: int) -> Centre:
        centre = await self.session.get(Centre, centre_id)
        if centre is None:
            raise NotFoundError("Diagnostic centre not found")
        return centre

    # ---- diagnostic tests ----------------------------------------------
    async def create_test(self, data: TestCreate) -> DiagnosticTest:
        test = DiagnosticTest(**data.model_dump())
        self.session.add(test)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError("A diagnostic test with this name already exists") from None
        return test

    async def list_tests(
        self, *, category: str | None, name: str | None, limit: int, offset: int
    ) -> tuple[list[DiagnosticTest], int]:
        conditions = []
        if category:
            conditions.append(DiagnosticTest.category.ilike(_like(category), escape="\\"))
        if name:
            conditions.append(DiagnosticTest.name.ilike(_like(name), escape="\\"))
        total = await self.session.scalar(select(func.count()).select_from(DiagnosticTest).where(*conditions)) or 0
        rows = await self.session.scalars(
            select(DiagnosticTest).where(*conditions).order_by(DiagnosticTest.name).limit(limit).offset(offset)
        )
        return list(rows), total

    async def get_test(self, test_id: int) -> DiagnosticTest:
        test = await self.session.get(DiagnosticTest, test_id)
        if test is None:
            raise NotFoundError("Diagnostic test not found")
        return test

    # ---- centre <-> test links -----------------------------------------
    async def list_centre_tests(self, centre_id: int) -> list[CentreTest]:
        await self.get_centre(centre_id)
        rows = await self.session.scalars(
            select(CentreTest)
            .join(DiagnosticTest, DiagnosticTest.id == CentreTest.test_id)
            .where(CentreTest.centre_id == centre_id)
            .order_by(DiagnosticTest.name)
        )
        return list(rows.unique())

    async def link_test(self, centre_id: int, data: CentreTestCreate) -> CentreTest:
        await self.get_centre(centre_id)
        await self.get_test(data.test_id)
        if await self.session.get(CentreTest, (centre_id, data.test_id)) is not None:
            raise ConflictError("This test is already offered by the centre; update its price instead")
        link = CentreTest(
            centre_id=centre_id, test_id=data.test_id, price=data.price, turnaround_hours=data.turnaround_hours
        )
        self.session.add(link)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError("This test is already offered by the centre; update its price instead") from None
        return await self._get_link(centre_id, data.test_id)

    async def update_link(self, centre_id: int, test_id: int, data: CentreTestUpdate) -> CentreTest:
        link = await self.session.get(CentreTest, (centre_id, test_id))
        if link is None:
            raise NotFoundError("This centre does not offer the specified test")
        if data.price is not None:
            link.price = data.price
        if data.turnaround_hours is not None:
            link.turnaround_hours = data.turnaround_hours
        await self.session.commit()
        return await self._get_link(centre_id, test_id)

    async def _get_link(self, centre_id: int, test_id: int) -> CentreTest:
        link = await self.session.scalar(
            select(CentreTest)
            .where(CentreTest.centre_id == centre_id, CentreTest.test_id == test_id)
            .execution_options(populate_existing=True)
        )
        assert link is not None
        return link
