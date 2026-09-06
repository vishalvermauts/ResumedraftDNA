from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.v1.health import router as health_router
from .api.v1.snapshots import router as snapshots_router
from .api.v1.scout import router as scout_router
from .api.v1.watchlist import router as watchlist_router
from .api.v1.tailor import router as tailor_router
from .api.v1.automation import router as automation_router
from .db.mongo import db
import os

configured_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "https://resumedraft.vercel.app,https://resumedraft-git-beta-version-vishalvermauts-projects.vercel.app",
)
allowed_origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]

app = FastAPI(title="ResumeDraft DNA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await db.connect()

@app.on_event("shutdown")
async def shutdown():
    await db.close()

app.include_router(health_router, prefix="/v1")
app.include_router(snapshots_router, prefix="/v1")
app.include_router(scout_router, prefix="/v1")
app.include_router(watchlist_router, prefix="/v1")
app.include_router(tailor_router, prefix="/v1")
app.include_router(automation_router, prefix="/v1")

@app.get("/")
def read_root():
    return {"message": "ResumeDraft DNA Backend"}
