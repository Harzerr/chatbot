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
    EMBEDDING_TIMEOUT: float = 15.0
    LLM_MODEL: str = "deepseek/deepseek-v4-flash"
    LLM_MAX_TOKENS: int = 512
    LLM_TIMEOUT: float = 30.0
    CAREER_LLM_MODEL: str = "deepseek/deepseek-v4-flash"
    # Career extraction returns detailed bullets plus an evidence map.
    CAREER_LLM_MAX_TOKENS: int = 1600
    CAREER_LLM_TIMEOUT: float = 30.0
    CAREER_RESUME_MAX_TOKENS: int = 5000
    CAREER_RESUME_TIMEOUT: float = 60.0
    # Interview traffic uses a model available in the server's OpenRouter region.
    INTERVIEW_LLM_MODEL: str = "deepseek/deepseek-v4-flash"
    INTERVIEW_LLM_MAX_TOKENS: int = 1024
    INTERVIEW_LLM_TIMEOUT: float = 30.0
    EVALUATION_LLM_MODEL: str = "deepseek/deepseek-v4-flash"
    EVALUATION_LLM_MAX_TOKENS: int = 1536
    EVALUATION_REASONING_EFFORT: str = "none"
    EVALUATION_LLM_TIMEOUT: float = 40.0
    EVALUATION_COMPACT_LLM_MAX_TOKENS: int = 768
    EVALUATION_COMPACT_LLM_TIMEOUT: float = 12.0
    # Keep memory extraction independent from the general-chat model's regional availability.
    MEMORY_LLM_MODEL: str = "deepseek/deepseek-v4-flash"
    PDFTOTEXT_PATH: str = ""
    RESUME_MAX_BYTES: int = 10 * 1024 * 1024
    RESUME_OCR_MAX_PAGES: int = 8
    RESUME_OCR_DPI: int = 144
    # 表示从简历中直接提取出的文字少于 80 个字符时，可能认为：这份 PDF 主要是扫描图片，普通文字提取效果不好，需要使用 OCR。
    RESUME_MIN_TEXT_CHARS: int = 80
    REDIS_URL: str = "redis://127.0.0.1:6379/1"
    RESUME_QUEUE_NAME: str = "resume_parse"
    # 单位s
    RESUME_QUEUE_TIMEOUT: int = 900
    CAREER_FACT_QUEUE_NAME: str = "career_fact_extraction"
    CAREER_FACT_QUEUE_TIMEOUT: int = 180
    CODE_QUEUE_NAME: str = "code_execution"
    CODE_QUEUE_TIMEOUT: int = 90
    EVALUATION_QUEUE_NAME: str = "interview_evaluation"
    EVALUATION_QUEUE_TIMEOUT: int = 180
    CONVERSATION_SUMMARY_QUEUE_NAME: str = "conversation_summary"
    CONVERSATION_SUMMARY_QUEUE_TIMEOUT: int = 180
    CONVERSATION_SUMMARY_TRIGGER_TURNS: int = 8
    CONVERSATION_SUMMARY_BATCH_TURNS: int = 4
    CONVERSATION_SUMMARY_RECENT_TURNS: int = 4
    CONVERSATION_SUMMARY_EVIDENCE_TURNS: int = 2
    CONVERSATION_SUMMARY_MAX_CHARS: int = 6000
    CONVERSATION_SUMMARY_SOURCE_MAX_CHARS: int = 20000
    CONVERSATION_SUMMARY_TIMEOUT: float = 45.0
    CONVERSATION_SUMMARY_LLM_MAX_TOKENS: int = 800
    CAREER_JOB_CACHE_TTL_SECONDS: int = 1800
    EVIDENCE_CACHE_TTL_SECONDS: int = 900
    EVIDENCE_CONTEXT_MAX_CHARS: int = 3200
    EVIDENCE_MAX_CHUNKS: int = 4
    EVIDENCE_CHUNK_MAX_CHARS: int = 900
    EVIDENCE_CHUNK_OVERLAP_CHARS: int = 120
    EVIDENCE_MAX_CHUNKS_PER_DOCUMENT: int = 2
    EVIDENCE_MIN_RETRIEVAL_SCORE: float = 0.05
    EVIDENCE_RETRIEVER_VERSION: str = "evidence-v4-project-claims"
    CAREER_EVIDENCE_VECTOR_ENABLED: bool = False
    CAREER_EVIDENCE_VECTOR_COLLECTION: str = "career_evidence"
    CAREER_EVIDENCE_VECTOR_TOP_K: int = 8
    CAREER_EVIDENCE_VECTOR_TIMEOUT: float = 10.0
    CAREER_EVIDENCE_HYBRID_LEXICAL_WEIGHT: float = 0.55
    CAREER_EVIDENCE_HYBRID_SEMANTIC_WEIGHT: float = 0.45
    CAREER_EVIDENCE_SEMANTIC_MIN_SCORE: float = 0.2
    CAREER_EVIDENCE_INDEX_QUEUE_NAME: str = "career_evidence_index"
    CAREER_EVIDENCE_INDEX_QUEUE_TIMEOUT: int = 180
    EVALUATION_CACHE_TTL_SECONDS: int = 86400
    EVALUATION_LOCK_TTL_SECONDS: int = 60
    EVALUATION_CACHE_VERSION: str = "evaluation-v1"
    OPENROUTER_RESPONSE_CACHE_ENABLED: bool = False
    OPENROUTER_RESPONSE_CACHE_TTL_SECONDS: int = 86400

    STT_API_URL: str = "http://127.0.0.1:8000/v1/"
    LLM_API_URL: str = "http://127.0.0.1:11434/v1/"
    TTS_API_URL: str = "http://127.0.0.1:3000/api/v1/"
    TTS_API_KEY: str = "********"

    SECRET_KEY: str = "********"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 300
    DEFAULT_TENANT_ID: str = "public"

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
    JUDGE0_POLL_INTERVAL: float = 0.5
    JUDGE0_CACHE_TTL_SECONDS: int = 900
    # Judge0 1.13 requires this mode on hosts using cgroup v2.
    JUDGE0_WINDOWS_COMPAT_MODE: bool = True
    JUDGE0_WINDOWS_MEMORY_LIMIT_KB: int = 1048576
    JUDGE0_JAVA_MEMORY_LIMIT_KB: int = 4194304
    MEM0_ADD_TIMEOUT: float = 20.0
    MEM0_ADD_RETRIES: int = 0
    MEM0_SEARCH_TIMEOUT: float = 10.0
    INTERVIEW_HISTORY_RECENT_TURNS: int = 4
    INTERVIEW_HISTORY_RELEVANT_TURNS: int = 6
    INTERVIEW_HISTORY_CONTEXT_MAX_CHARS: int = 12000
    INTERVIEW_HISTORY_SEARCH_TIMEOUT: float = 5.0
    LLM_INPUT_USD_PER_1M: float = 0.0
    LLM_OUTPUT_USD_PER_1M: float = 0.0

    TAVILY_API_KEY: str = "********"
    FIRECRAWL_API_KEY: str = "********"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
