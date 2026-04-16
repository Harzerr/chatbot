import base64
import subprocess
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

SUPPORTED_RESUME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}


class ResumeParserService:
    def __init__(self) -> None:
        self._vision_llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
        )

    async def extract_text(self, file_path: str, content_type: str) -> str:
        if content_type == "application/pdf":
            return self._extract_pdf_text(file_path)

        if content_type in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            return await self._extract_image_text(file_path, content_type)

        raise ValueError("Unsupported resume file type")

    def _extract_pdf_text(self, file_path: str) -> str:
        result = subprocess.run(
            ["pdftotext", "-layout", file_path, "-"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "Failed to extract text from PDF")

        text = (result.stdout or "").strip()
        if not text:
            raise ValueError("The uploaded PDF does not contain readable text")
        return text

    async def _extract_image_text(self, file_path: str, content_type: str) -> str:
        image_bytes = Path(file_path).read_bytes()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Please extract the resume text from this image as faithfully as possible. "
                        "Preserve section headings, bullet points, dates, skills, education, and project details. "
                        "Return plain text only."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                },
            ]
        )

        response = await self._vision_llm.ainvoke([message])
        text = (response.content if hasattr(response, "content") else str(response)).strip()
        if not text:
            raise ValueError("The uploaded image could not be parsed into resume text")
        return text
