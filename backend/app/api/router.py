"""API v1 router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import analytics, businesses, content, generation, leads, prompts, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(businesses.router)
api_router.include_router(content.router)
api_router.include_router(generation.router)
api_router.include_router(prompts.router)
api_router.include_router(analytics.router)
api_router.include_router(leads.router)
api_router.include_router(system.admin_router)

#: Health + webhook live at the root, outside the versioned prefix.
system_router = APIRouter()
system_router.include_router(system.router)

__all__ = ["api_router", "system_router"]
