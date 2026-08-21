from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


USER_PROFILE_COLUMNS = {
    "full_name": "ALTER TABLE users ADD COLUMN full_name VARCHAR NOT NULL DEFAULT ''",
    "email": "ALTER TABLE users ADD COLUMN email VARCHAR NOT NULL DEFAULT ''",
    "phone": "ALTER TABLE users ADD COLUMN phone VARCHAR NOT NULL DEFAULT ''",
    "target_role": "ALTER TABLE users ADD COLUMN target_role VARCHAR NOT NULL DEFAULT ''",
    "years_of_experience": "ALTER TABLE users ADD COLUMN years_of_experience INTEGER NOT NULL DEFAULT 0",
    "bio": "ALTER TABLE users ADD COLUMN bio TEXT",
    "resume_file_name": "ALTER TABLE users ADD COLUMN resume_file_name VARCHAR",
    "resume_file_path": "ALTER TABLE users ADD COLUMN resume_file_path VARCHAR",
    "resume_content_type": "ALTER TABLE users ADD COLUMN resume_content_type VARCHAR",
    "resume_uploaded_at": "ALTER TABLE users ADD COLUMN resume_uploaded_at VARCHAR",
    "resume_text": "ALTER TABLE users ADD COLUMN resume_text TEXT",
    "avatar_file_name": "ALTER TABLE users ADD COLUMN avatar_file_name VARCHAR",
    "avatar_file_path": "ALTER TABLE users ADD COLUMN avatar_file_path VARCHAR",
    "avatar_content_type": "ALTER TABLE users ADD COLUMN avatar_content_type VARCHAR",
    "avatar_updated_at": "ALTER TABLE users ADD COLUMN avatar_updated_at VARCHAR",
    "education_json": "ALTER TABLE users ADD COLUMN education_json TEXT NOT NULL DEFAULT '[]'",
}

AI_METRIC_COLUMNS = {
    "model_latency_ms": "ALTER TABLE ai_request_metrics ADD COLUMN model_latency_ms FLOAT NOT NULL DEFAULT 0",
    "queue_wait_ms": "ALTER TABLE ai_request_metrics ADD COLUMN queue_wait_ms FLOAT NOT NULL DEFAULT 0",
    "total_tokens": "ALTER TABLE ai_request_metrics ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0",
    "cache_hit": "ALTER TABLE ai_request_metrics ADD COLUMN cache_hit INTEGER NOT NULL DEFAULT 0",
    "attempt": "ALTER TABLE ai_request_metrics ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1",
    "evidence_retrieval_count": "ALTER TABLE ai_request_metrics ADD COLUMN evidence_retrieval_count INTEGER NOT NULL DEFAULT 0",
    "evidence_context_chars": "ALTER TABLE ai_request_metrics ADD COLUMN evidence_context_chars INTEGER NOT NULL DEFAULT 0",
    "evidence_cache_hit": "ALTER TABLE ai_request_metrics ADD COLUMN evidence_cache_hit INTEGER NOT NULL DEFAULT 0",
    "evidence_retrieval_method": "ALTER TABLE ai_request_metrics ADD COLUMN evidence_retrieval_method VARCHAR(64) NOT NULL DEFAULT 'none'",
}


async def ensure_user_profile_columns(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(users)"))
        existing_columns = {row[1] for row in result.fetchall()}

        for column_name, ddl in USER_PROFILE_COLUMNS.items():
            if column_name in existing_columns:
                continue

            logger.info("Adding missing users.%s column", column_name)
            await conn.execute(text(ddl))


async def ensure_training_columns(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(training_items)"))
        existing = {row[1] for row in result.fetchall()}
        for name, ddl in {
            "due_at": "ALTER TABLE training_items ADD COLUMN due_at DATETIME",
            "job_id": "ALTER TABLE training_items ADD COLUMN job_id INTEGER",
        }.items():
            if name not in existing:
                await conn.execute(text(ddl))
        result = await conn.execute(text("PRAGMA table_info(training_attempts)"))
        existing = {row[1] for row in result.fetchall()}
        if "evaluation_json" not in existing:
            await conn.execute(text("ALTER TABLE training_attempts ADD COLUMN evaluation_json TEXT NOT NULL DEFAULT '{}'"))


async def ensure_career_knowledge_columns(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(career_knowledge_documents)"))
        existing = {row[1] for row in result.fetchall()}
        if existing and "fact_id" not in existing:
            await conn.execute(text("ALTER TABLE career_knowledge_documents ADD COLUMN fact_id INTEGER"))

        result = await conn.execute(text("PRAGMA table_info(career_knowledge_chunks)"))
        chunk_columns = {row[1] for row in result.fetchall()}
        for name, ddl in {
            "project_key": "ALTER TABLE career_knowledge_chunks ADD COLUMN project_key VARCHAR(128) NOT NULL DEFAULT ''",
            "claim_ids_json": "ALTER TABLE career_knowledge_chunks ADD COLUMN claim_ids_json TEXT NOT NULL DEFAULT '[]'",
            "claim_texts_json": "ALTER TABLE career_knowledge_chunks ADD COLUMN claim_texts_json TEXT NOT NULL DEFAULT '[]'",
        }.items():
            if chunk_columns and name not in chunk_columns:
                await conn.execute(text(ddl))


async def ensure_ai_metric_columns(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(ai_request_metrics)"))
        existing = {row[1] for row in result.fetchall()}
        for name, ddl in AI_METRIC_COLUMNS.items():
            if name not in existing:
                logger.info("Adding missing ai_request_metrics.%s column", name)
                await conn.execute(text(ddl))
