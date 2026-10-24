"""FastAPI application entry point for Customer Support Resolution Agent."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.api import api_router
from app.db.session import init_db
from scripts.seed_data import seed

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT == "production":
        if settings.AUTH_MODE != "oidc" or not settings.OIDC_ISSUER:
            raise RuntimeError("Production requires configured OIDC authentication.")
        if settings.AUTO_CREATE_SCHEMA or settings.SEED_DEMO_DATA or not settings.ASYNC_WORKFLOWS:
            raise RuntimeError("Production requires migrations, a dedicated worker and demo seeding disabled.")
        if not settings.DATABASE_URL.startswith("postgresql"):
            raise RuntimeError("Production requires PostgreSQL.")
        if settings.SECRET_KEY.startswith("super-secret-dev"):
            raise RuntimeError("Production requires a strong non-default SECRET_KEY.")
    if settings.AUTO_CREATE_SCHEMA:
        await init_db()
    if settings.SEED_DEMO_DATA:
        await seed()
    from app.workflows.checkpoints import checkpoint_store
    async with checkpoint_store():
        pass
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Customer Support Resolution Agent with policy retrieval, human approvals, and idempotent refund execution.",
    lifespan=lifespan
)

from app.api.middleware import request_controls
app.middleware("http")(request_controls)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Mount API routes
app.include_router(api_router, prefix="/api")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serves the interactive web UI dashboard."""
    return templates.TemplateResponse(request=request, name="index.html", context={"project_name": settings.PROJECT_NAME})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
