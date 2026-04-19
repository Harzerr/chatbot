import base64
import shutil
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
        configured_pdftotext = (settings.PDFTOTEXT_PATH or "").strip()
        self._pdftotext_cmd = configured_pdftotext or shutil.which("pdftotext")

    async def extract_text(self, file_path: str, content_type: str) -> str:
        if content_type == "application/pdf":
            return self._extract_pdf_text(file_path)

        if content_type in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            return await self._extract_image_text(file_path, content_type)

        raise ValueError("Unsupported resume file type")

    def _extract_pdf_text(self, file_path: str) -> str:
        errors: list[str] = []

        if self._pdftotext_cmd:
            try:
                result = subprocess.run(
                    [self._pdftotext_cmd, "-layout", file_path, "-"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    text = (result.stdout or "").strip()
                    if text:
                        return text
                    errors.append("pdftotext returned empty output")
                else:
                    errors.append(result.stderr.strip() or "pdftotext failed")
            except FileNotFoundError:
                errors.append(f"pdftotext not found at '{self._pdftotext_cmd}'")
            except Exception as exc:
                errors.append(f"pdftotext error: {exc}")
        else:
            errors.append("pdftotext executable is not available in PATH")

        try:
            return self._extract_pdf_text_with_python(file_path)
        except Exception as exc:
            errors.append(str(exc))

        logger.warning("PDF text extraction failed for %s. reasons=%s", file_path, " | ".join(errors))
        raise ValueError(
            "Failed to extract text from PDF. Install Poppler (pdftotext) or set PDFTOTEXT_PATH, "
            "or install pypdf/PyPDF2 for Python fallback."
        )

    def _extract_pdf_text_with_python(self, file_path: str) -> str:
        pdf_reader_cls = None
        import_error: Exception | None = None

        try:
            from pypdf import PdfReader

            pdf_reader_cls = PdfReader
        except Exception as exc:
            import_error = exc
            try:
                from PyPDF2 import PdfReader

                pdf_reader_cls = PdfReader
            except Exception:
                pdf_reader_cls = None

        if pdf_reader_cls is None:
            raise ValueError(
                "Python PDF parser unavailable. Install pypdf (recommended) or PyPDF2."
            ) from import_error

        try:
            reader = pdf_reader_cls(file_path)
            pages = []
            for page in reader.pages:
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    pages.append(page_text)
            text = "\n\n".join(pages).strip()
        except Exception as exc:
            raise ValueError(f"Python PDF parser failed: {exc}") from exc

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
