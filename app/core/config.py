from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "AI General Chatbot"

    BACKEND_CORS_ORIGINS: List[str] = ["*"]
    @classmethod
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    LIVEKIT_URL: str = "ws://127.0.0.1:7880"
    LIVEKIT_INTERNAL_URL: str = "ws://127.0.0.1:7880"
    LIVEKIT_PUBLIC_URL: str = "ws://127.0.0.1:7880"
    LIVEKIT_API_KEY: str = "********"
    LIVEKIT_API_SECRET: str = "********"
    LIVEKIT_API_HTTP_PROXY: str = ""
    LIVEKIT_AGENT_HTTP_PROXY: str = ""
    LIVEKIT_AGENT_RTC_RELAY_ONLY: bool = False
    LIVEKIT_ENABLE_TURN_DETECTION: bool = False
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_LANGUAGE: str = "zh-CN"
    STT_CONNECT_TIMEOUT: float = 30.0
    STT_CONNECT_MAX_RETRIES: int = 3
    STT_CONNECT_RETRY_INTERVAL: float = 2.0
    CARTESIA_API_KEY: str = ""
    CARTESIA_VOICE_ID: str = "4f8651b0-bbbd-46ac-8b37-5168c5923303"
    CARTESIA_LANGUAGE: str = "zh"

    OPENROUTER_API_KEY: str = "********"
    OPENROUTER_API_BASE: str = "https://openrouter.ai/api/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 768
    EMBEDDING_MAX_RETRIES: int = 2
    EMBEDDING_RETRY_INTERVAL: float = 0.8
    LLM_MODEL: str = "openai/gpt-4o-mini"

    STT_API_URL: str = "http://127.0.0.1:8000/v1/"
    LLM_API_URL: str = "http://127.0.0.1:11434/v1/"
    TTS_API_URL: str = "http://127.0.0.1:3000/api/v1/"
    TTS_API_KEY: str = "********"

    SECRET_KEY: str = "********"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 300

    SQLALCHEMY_DATABASE_URI: str = "sqlite:///./app.db"

    LANGCHAIN_TRACING_V2: bool = 'true'
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: str= "********"
    LANGSMITH_PROJECT: str = "pr-only-surround-27"

    QDRANT_PORT: int = 6333
    QDRANT_HOST: str = "localhost"
    QDRANT_TIMEOUT: float = 30.0
    QDRANT_ROLE_KNOWLEDGE_COLLECTION: str = "interview_role_knowledge"
    QDRANT_CODING_KNOWLEDGE_COLLECTION: str = "interview_coding_knowledge"
    JUDGE0_API_URL: str = "http://127.0.0.1:2358"
    JUDGE0_API_KEY: str = ""
    JUDGE0_TIMEOUT: float = 20.0
    JUDGE0_WINDOWS_COMPAT_MODE: bool = False
    JUDGE0_WINDOWS_MEMORY_LIMIT_KB: int = 1048576
    MEM0_ADD_TIMEOUT: float = 20.0
    MEM0_ADD_RETRIES: int = 1
    MEM0_SEARCH_TIMEOUT: float = 10.0

    TAVILY_API_KEY: str = "********"
    FIRECRAWL_API_KEY: str = "********"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
