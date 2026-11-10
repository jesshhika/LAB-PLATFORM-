from fastapi import FastAPI

from api.app.routes import router as api_router

app = FastAPI(title="LabForge API", version="0.1.0")
app.include_router(api_router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "api"}
