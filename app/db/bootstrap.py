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
