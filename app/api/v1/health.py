from fastapi import APIRouter, Depends
from ...auth import get_current_user

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

@router.get("/auth-test")
async def auth_test(user: dict = Depends(get_current_user)):
    return {"status": "authenticated", "uid": user["uid"]}
