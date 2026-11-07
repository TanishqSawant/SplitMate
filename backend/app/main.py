"""SplitMate FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import expenses, groups, health, payments, receipts
from app.core.config import settings

app = FastAPI(
    title="SplitMate API",
    description="AI-powered group expense management platform",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allows Dhruv's React frontend to call the API
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(receipts.router)
app.include_router(groups.router)
app.include_router(expenses.router)
app.include_router(payments.router)

