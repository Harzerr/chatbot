import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.langgraph_agent import initialize_graph, close_graph
from app.api.api import api_router
from app.core.config import settings
from app.db.bootstrap import ensure_user_profile_columns
from app.db.base import Base
from app.db.session import async_engine
from app.services.role_knowledge_store import QdrantRoleKnowledgeStore
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

    logger.info(f"LANGCHAIN_TRACING_V2: {os.getenv('LANGCHAIN_TRACING_V2')}")
    logger.info(f"LANGSMITH_PROJECT: {os.getenv('LANGSMITH_PROJECT')}")

    yield

    await async_engine.dispose()
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

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
