"""Tests for API endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "ClipForge AI"


@pytest.mark.asyncio
async def test_list_jobs_empty(client: AsyncClient):
    response = await client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["jobs"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_job_not_found(client: AsyncClient):
    response = await client.get("/api/jobs/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_no_file(client: AsyncClient):
    response = await client.post("/api/videos/upload")
    assert response.status_code == 422  # Missing required file


@pytest.mark.asyncio
async def test_upload_invalid_extension(client: AsyncClient):
    response = await client.post(
        "/api/videos/upload",
        files={"file": ("test.txt", b"not a video", "text/plain")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_empty_file(client: AsyncClient):
    response = await client.post(
        "/api/videos/upload",
        files={"file": ("test.mp4", b"", "video/mp4")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_brand_profile_default(client: AsyncClient):
    response = await client.get("/api/brand-profile")
    assert response.status_code == 200
    data = response.json()
    assert data["brand_name"] == "ClipForge AI"


@pytest.mark.asyncio
async def test_clip_not_found(client: AsyncClient):
    response = await client.post("/api/clips/nonexistent/approve")
    assert response.status_code == 404
