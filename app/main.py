from fastapi import FastAPI
from .api.v1.health import router as health_router
from .api.v1.snapshots import router as snapshots_router
from .api.v1.scout import router as scout_router
from .api.v1.watchlist import router as watchlist_router
from .api.v1.tailor import router as tailor_router
from .db.mongo import db

app = FastAPI(title="ResumeDraft DNA API")

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

@app.get("/")
def read_root():
    return {"message": "ResumeDraft DNA Backend"}
