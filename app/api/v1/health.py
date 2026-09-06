from fastapi import APIRouter, Depends
from ...auth import get_current_user
import os

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok", "version": os.getenv("APP_VERSION", "unknown")}

@router.get("/auth-test")
async def auth_test(user: dict = Depends(get_current_user)):
    return {"status": "authenticated", "uid": user["uid"]}
