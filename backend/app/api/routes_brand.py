"""Brand profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import BrandRepository
from app.db.session import get_db
from app.schemas.brand import BrandProfile, BrandProfileUpdate

router = APIRouter(prefix="/api/brand-profile", tags=["brand"])


@router.get("", response_model=BrandProfile)
async def get_brand_profile(
    db: AsyncSession = Depends(get_db),
) -> BrandProfile:
    """Get the current brand profile."""
    repo = BrandRepository(db)
    return await repo.get()


@router.put("", response_model=BrandProfile)
async def update_brand_profile(
    update: BrandProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> BrandProfile:
    """Update the brand profile (partial update)."""
    repo = BrandRepository(db)
    current = await repo.get()

    # Apply partial update
    update_data = update.model_dump(exclude_unset=True)
    updated = current.model_copy(update=update_data)

    return await repo.upsert(updated)
