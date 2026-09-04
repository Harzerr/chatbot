import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.langgraph_agent import initialize_graph, close_graph
from app.api.api import api_router
from app.core.config import settings
from app.db.bootstrap import (
    ensure_ai_metric_columns,
    ensure_career_knowledge_columns,
    ensure_training_columns,
    ensure_user_profile_columns,
)
from app.db.base import Base
from app.db.session import async_engine
from app.services.role_knowledge_store import QdrantRoleKnowledgeStore
from app.services.resume_jobs import recover_pending_resume_parse_jobs
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await initialize_graph()
    except Exception:
        logger.exception(
            "Chat graph initialization failed during startup. Core API routes will remain available, but chat features may be degraded."
        )

    try:
        QdrantRoleKnowledgeStore()
    except Exception as exc:
        logger.warning(
            "Skipping role knowledge store warm-up because Qdrant is unavailable during startup: %s",
            exc,
        )

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_user_profile_columns(async_engine)
    await ensure_training_columns(async_engine)
    await ensure_career_knowledge_columns(async_engine)
    await ensure_ai_metric_columns(async_engine)
    resume_recovery_task = asyncio.create_task(recover_pending_resume_parse_jobs())

    logger.info(f"LANGCHAIN_TRACING_V2: {os.getenv('LANGCHAIN_TRACING_V2')}")
    logger.info(f"LANGSMITH_PROJECT: {os.getenv('LANGSMITH_PROJECT')}")

    yield

    await async_engine.dispose()
    resume_recovery_task.cancel()
    try:
        await resume_recovery_task
    except asyncio.CancelledError:
        pass
    try:
        await close_graph()
    except Exception:
        logger.exception("Failed to close chat graph cleanly during shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

AVATAR_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "avatars"
AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media/avatars", StaticFiles(directory=str(AVATAR_UPLOAD_DIR)), name="avatar-media")

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
if FONT_DIR.is_dir():
    app.mount(f"{settings.API_V1_STR}/fonts", StaticFiles(directory=str(FONT_DIR)), name="font-media")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
