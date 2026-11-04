from fastapi import FastAPI

app = FastAPI(title="LabForge API", version="0.1.0")


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "api"}
