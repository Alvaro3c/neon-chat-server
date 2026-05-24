from fastapi import APIRouter
from typing import TypedDict

from app.ws.manager import manager

router = APIRouter()


class HealthResponse(TypedDict):
    status: str
    connected_users: int


@router.get("/health", response_model=None)
async def health_check() -> HealthResponse:
    return {"status": "ok", "connected_users": manager.connected_count()}
