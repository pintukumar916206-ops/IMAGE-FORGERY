from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from backend.app.api.routes import UPLOAD_DIR, limiter, router
from backend.app.core.config import settings
from backend.app.services.tasks import shutdown_executor, start_cleanup_worker, stop_cleanup_worker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path("backend/logs").mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    start_cleanup_worker(UPLOAD_DIR)
    try:
        yield
    finally:
        await stop_cleanup_worker(UPLOAD_DIR)
        shutdown_executor()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(router)

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again later."})


@app.get("/")
def root():
    return {"message": settings.PROJECT_NAME, "method": "forensic"}


if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "Not Found")})
        return FileResponse("frontend/dist/index.html")
