from fastapi import APIRouter
from app.api.complaints import router as complaints_router
from app.api.tickets import router as tickets_router
from app.api.approvals import router as approvals_router
from app.api.workflows import router as workflows_router
from app.api.health import router as health_router
from app.api.webhooks import router as webhook_router

from app.api.operations import router as operations_router

api_router = APIRouter()
api_router.include_router(operations_router)
api_router.include_router(health_router)
api_router.include_router(complaints_router)
api_router.include_router(tickets_router)
api_router.include_router(approvals_router)
api_router.include_router(workflows_router)
api_router.include_router(webhook_router)

__all__ = ["api_router"]
