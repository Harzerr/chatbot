import asyncio
import base64
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
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


@dataclass
class ParsedPage:
    page_number: int
    text: str


@dataclass
class ResumeParseResult:
    text: str
    pages: list[ParsedPage]
    parser_name: str
    warnings: list[str] = field(default_factory=list)
    quality_score: float = 0.0


class ResumeParserService:
    def __init__(self) -> None:
        self._vision_llm: ChatOpenAI | None = None
        configured_pdftotext = (settings.PDFTOTEXT_PATH or "").strip()
        self._pdftotext_cmd = configured_pdftotext or shutil.which("pdftotext")

    def _get_vision_llm(self) -> ChatOpenAI:
        if self._vision_llm is None:
            self._vision_llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                temperature=0,
                api_key=settings.OPENROUTER_API_KEY,
                base_url=settings.OPENROUTER_API_BASE,
            )
        return self._vision_llm

    async def parse(self, file_path: str, content_type: str) -> ResumeParseResult:
        if content_type == "application/pdf":
            return await self._parse_pdf(file_path)

        if content_type in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            return await self._parse_image(file_path, content_type)

        raise ValueError("Unsupported resume file type")

    async def extract_text(self, file_path: str, content_type: str) -> str:
        """Backward-compatible text-only API for existing callers."""
        result = await self.parse(file_path, content_type)
        return result.text

    async def _parse_pdf(self, file_path: str) -> ResumeParseResult:
        raw_text, extraction_errors = await asyncio.to_thread(self._run_pdftotext, file_path)
        page_texts: list[str] = []

        try:
            page_texts = await asyncio.to_thread(self._extract_pdf_pages_with_python, file_path)
        except Exception as exc:
            extraction_errors.append(str(exc))

        if self._has_usable_text(raw_text):
            pages = self._build_pages(page_texts or self._split_pages(raw_text))
            warnings = []
            if not page_texts:
                warnings.append("文本已提取，但未能恢复准确的页级结构")
            return ResumeParseResult(
                text=self._join_pages(pages, raw_text),
                pages=pages,
                parser_name="pdftotext",
                warnings=warnings,
                quality_score=self._quality_score(raw_text),
            )

        if page_texts:
            fallback_text = self._join_pages(self._build_pages(page_texts))
            if self._has_usable_text(fallback_text):
                return ResumeParseResult(
                    text=fallback_text,
                    pages=self._build_pages(page_texts),
                    parser_name="pypdf",
                    warnings=["pdftotext 未提取到文本，已使用 Python PDF 解析器"],
                    quality_score=self._quality_score(fallback_text),
                )

        logger.info("PDF has no usable text; switching to OCR. reasons=%s", extraction_errors)
        return await self._parse_pdf_with_ocr(file_path, extraction_errors)

    async def _parse_image(self, file_path: str, content_type: str) -> ResumeParseResult:
        image_bytes = Path(file_path).read_bytes()
        text = await self._extract_image_bytes_text(image_bytes, content_type)
        page = ParsedPage(page_number=1, text=text)
        return ResumeParseResult(
            text=text,
            pages=[page],
            parser_name="vision_ocr",
            warnings=[],
            quality_score=self._quality_score(text),
        )

    def _run_pdftotext(self, file_path: str) -> tuple[str, list[str]]:
        errors: list[str] = []
        if not self._pdftotext_cmd:
            return "", ["pdftotext executable is not available in PATH"]

        try:
            result = subprocess.run(
                [self._pdftotext_cmd, "-layout", file_path, "-"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode == 0 and (result.stdout or "").strip():
                return result.stdout.strip(), errors
            errors.append(result.stderr.strip() or "pdftotext returned empty output")
        except FileNotFoundError:
            errors.append(f"pdftotext not found at '{self._pdftotext_cmd}'")
        except subprocess.TimeoutExpired:
            errors.append("pdftotext timed out")
        except Exception as exc:
            errors.append(f"pdftotext error: {exc}")
        return "", errors

    def _extract_pdf_pages_with_python(self, file_path: str) -> list[str]:
        try:
            from pypdf import PdfReader
        except Exception as import_error:
            raise ValueError("Python PDF parser unavailable; install pypdf") from import_error

        try:
            reader = PdfReader(file_path)
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
        except Exception as exc:
            raise ValueError(f"Python PDF parser failed: {exc}") from exc
        return pages

    async def _parse_pdf_with_ocr(self, file_path: str, extraction_errors: list[str]) -> ResumeParseResult:
        pages: list[ParsedPage] = []
        warnings = ["PDF 文本层不可用，已切换到视觉 OCR"]
        if extraction_errors:
            warnings.append(f"文本解析回退原因：{extraction_errors[0]}")

        max_pages = max(1, settings.RESUME_OCR_MAX_PAGES)
        rendered_pages, page_count, renderer_warning = await self._render_pdf_pages(file_path, max_pages)
        if renderer_warning:
            warnings.append(renderer_warning)

        for index, image_bytes in enumerate(rendered_pages):
            try:
                text = await self._extract_image_bytes_text(image_bytes, "image/png")
            except Exception as exc:
                warnings.append(f"第 {index + 1} 页 OCR 失败：{exc}")
                continue
            if text.strip():
                pages.append(ParsedPage(page_number=index + 1, text=text.strip()))

        text = self._join_pages(pages)
        if not self._has_usable_text(text):
            raise ValueError("OCR 未能从该 PDF 中提取出足够的简历文本")
        return ResumeParseResult(
            text=text,
            pages=pages,
            parser_name="vision_ocr",
            warnings=warnings,
            quality_score=self._quality_score(text),
        )

    async def _render_pdf_pages(self, file_path: str, max_pages: int) -> tuple[list[bytes], int, str | None]:
        try:
            import fitz

            document = await asyncio.to_thread(fitz.open, file_path)
            page_count = len(document)
            rendered: list[bytes] = []
            try:
                for index in range(min(page_count, max_pages)):
                    rendered.append(await asyncio.to_thread(self._render_pdf_page, document[index], fitz))
            finally:
                document.close()
            warning = f"文档共 {page_count} 页，仅 OCR 前 {max_pages} 页" if page_count > max_pages else None
            return rendered, page_count, warning
        except ImportError:
            pass

        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            raise ValueError(
                "该 PDF 没有可读取的文本层，服务器未安装 PDF 渲染工具，无法执行 OCR。"
                "请安装 PyMuPDF 或 poppler-utils。"
            )

        rendered = []
        for page_number in range(1, max_pages + 1):
            image_bytes = await asyncio.to_thread(
                self._render_pdf_page_with_pdftoppm,
                pdftoppm,
                file_path,
                page_number,
            )
            if not image_bytes:
                break
            rendered.append(image_bytes)
        if not rendered:
            raise ValueError("PDF 页面渲染失败，无法执行 OCR")
        warning = "使用 poppler-utils 渲染 PDF 页面；页数以成功渲染的页面为准"
        return rendered, len(rendered), warning

    @staticmethod
    def _render_pdf_page_with_pdftoppm(pdftoppm: str, file_path: str, page_number: int) -> bytes:
        with tempfile.TemporaryDirectory(prefix="resume-ocr-") as directory:
            output_prefix = str(Path(directory) / "page")
            result = subprocess.run(
                [
                    pdftoppm,
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-r",
                    str(settings.RESUME_OCR_DPI),
                    "-png",
                    "-singlefile",
                    file_path,
                    output_prefix,
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
            if result.returncode != 0:
                return b""
            image_path = Path(f"{output_prefix}.png")
            return image_path.read_bytes() if image_path.is_file() else b""

    @staticmethod
    def _render_pdf_page(page, fitz_module) -> bytes:
        scale = max(1.0, settings.RESUME_OCR_DPI / 72)
        pixmap = page.get_pixmap(matrix=fitz_module.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")

    async def _extract_image_bytes_text(self, image_bytes: bytes, content_type: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "请忠实提取这张简历图片中的文字。保留章节标题、项目符号、日期、"
                        "学校、公司、岗位、技能和项目细节。按原始阅读顺序返回纯文本，不要补充原图没有的信息。"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                },
            ]
        )
        response = await self._get_vision_llm().ainvoke([message])
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        text = str(content).strip()
        if not text:
            raise ValueError("视觉模型没有返回可用文本")
        return text

    @staticmethod
    def _split_pages(text: str) -> list[str]:
        return [part.strip() for part in text.split("\f") if part.strip()]

    @staticmethod
    def _build_pages(page_texts: list[str]) -> list[ParsedPage]:
        return [
            ParsedPage(page_number=index + 1, text=text.strip())
            for index, text in enumerate(page_texts)
            if text.strip()
        ]

    @staticmethod
    def _join_pages(pages: list[ParsedPage], fallback: str = "") -> str:
        return "\n\n".join(page.text for page in pages if page.text.strip()).strip() or fallback.strip()

    @staticmethod
    def _has_usable_text(text: str) -> bool:
        return len("".join((text or "").split())) >= settings.RESUME_MIN_TEXT_CHARS

    @staticmethod
    def _quality_score(text: str) -> float:
        char_count = len("".join((text or "").split()))
        return round(min(1.0, char_count / 2000), 3)
