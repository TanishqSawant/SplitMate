"""SplitMate FastAPI application entry point."""

from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import auth, expenses, groups, health, payments, receipts
from app.core.config import settings
from app.db.session import Base, engine
import app.models.models  # Ensure all ORM models are registered

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables for local/SQLite dev setups only
    # In production with PostgreSQL, schema is managed via Alembic migrations
    if settings.DATABASE_URL.startswith("sqlite") and settings.APP_ENV != "production":
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="SplitMate API",
    description="AI-powered group expense management platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allows Dhruv's React frontend to call the API
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Attach unique X-Request-ID for distributed log tracing."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(receipts.router)
app.include_router(groups.router)
app.include_router(expenses.router)
app.include_router(payments.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Production exception handler: log detailed traceback on server, return safe JSON to client."""
    logger.error("Unhandled exception processing %s %s: %s", request.method, request.url.path, exc, exc_info=settings.DEBUG)
    if settings.DEBUG:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error: {str(exc)}"},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."},
    )

