from fastapi import FastAPI
from .api.v1.health import router as health_router

app = FastAPI(title="ResumeDraft DNA API")

app.include_router(health_router, prefix="/v1")

@app.get("/")
def read_root():
    return {"message": "ResumeDraft DNA Backend"}
