from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.schemas.chat import InterviewReportResponse


class InterviewReportPdfError(RuntimeError):
    """Raised when the server cannot compile the interview report PDF."""


class InterviewReportPdfBuilder:
    """Render a stable, selectable-text interview report with XeLaTeX."""

    _score_fields = (
        ("technical_accuracy", "技术准确性"),
        ("knowledge_depth", "知识深度"),
        ("communication_clarity", "表达清晰度"),
        ("logical_structure", "逻辑结构"),
        ("problem_solving", "问题解决能力"),
        ("job_match_score", "岗位匹配度"),
    )

    @staticmethod
    def _tex(value: object) -> str:
        text = str(value or "")
        replacements = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        return "".join(replacements.get(char, char) for char in text)

    @classmethod
    def _paragraph(cls, value: object, fallback: str = "暂无内容。") -> str:
        text = str(value or "").strip() or fallback
        paragraphs = re.split(r"\n\s*\n", text)
        return "\n\n".join(cls._tex(item.strip()).replace("\n", " ") for item in paragraphs if item.strip())

    @staticmethod
    def _is_code_answer(answer: str, evaluation: object) -> bool:
        question_type = str(getattr(evaluation, "question_type", "") or "")
        if question_type == "代码题":
            return True
        return bool(re.search(r"```|#include\s*[<\"]|\bclass\s+Solution\b|\bdef\s+\w+\s*\(|\bfunction\s+\w+", answer))

    @staticmethod
    def _code_block(value: object) -> str:
        text = str(value or "").strip()
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).replace("\\end{Verbatim}", "\\end{ Verbatim}")
        return "\\begin{Verbatim}[fontsize=\\small,frame=single,breaklines=true,breakanywhere=true]\n" + text + "\n\\end{Verbatim}\n"

    @classmethod
    def _items(cls, values: list[str] | None, fallback: str) -> str:
        items = [str(item).strip() for item in (values or []) if str(item).strip()]
        if not items:
            items = [fallback]
        return "\n".join(f"\\item {cls._tex(item)}" for item in items)

    @classmethod
    def _score_rows(cls, report: InterviewReportResponse) -> str:
        rows = []
        for field, label in cls._score_fields:
            value = getattr(report, field, None)
            if value is None:
                continue
            rows.append(f"{cls._tex(label)} & {cls._tex(value)} & & \\\\")
        return "\n".join(rows)

    @classmethod
    def _competency_rows(cls, report: InterviewReportResponse) -> str:
        rows = []
        for item in report.competency_assessments:
            evidence = (item.evidence[0] if item.evidence else "已记录作答，尚缺少独立材料")[:150]
            rows.append(
                " & ".join(
                    [
                        cls._tex(item.capability),
                        cls._tex(item.score),
                        cls._tex(f"{item.covered_questions} 题 / {item.confidence}置信度"),
                        cls._tex(evidence),
                    ]
                )
                + r" \\" 
            )
        return "\n".join(rows) or "暂无有效能力覆盖数据。"

    @classmethod
    def _question_blocks(cls, report: InterviewReportResponse) -> str:
        blocks = []
        for index, item in enumerate(report.interview_questions, start=1):
            evaluation = item.evaluation
            if item.evaluation_status == "queued":
                evaluation_text = "已进入评估队列，等待处理。"
            elif item.evaluation_status == "processing":
                evaluation_text = "正在评估本题。"
            elif item.evaluation_status == "failed":
                evaluation_text = f"评估失败：{item.evaluation_error or '评估服务暂时不可用。'}"
            elif evaluation:
                evaluation_text = f"综合得分：{evaluation.overall_score}。{evaluation.summary or ''}".strip()
            else:
                evaluation_text = "暂无评估结果。"

            candidate_answer = item.candidate_answer or ""
            candidate_rendered = (
                cls._code_block(candidate_answer)
                if cls._is_code_answer(candidate_answer, evaluation)
                else cls._paragraph(candidate_answer, "未记录回答")
            )
            blocks.append(
                "\\subsection*{" + cls._tex(f"第 {index} 题") + "}\n"
                + "\\textbf{面试官问题}\\par\n"
                + cls._paragraph(item.question, "未记录问题")
                + "\\par\\smallskip\\textbf{候选人回答}\\par\n"
                + candidate_rendered
                + "\\par\\smallskip\\textbf{本题评估}\\par\n"
                + cls._paragraph(evaluation_text)
                + "\\par\\smallskip\\textbf{参考答案}\\par\n"
                + cls._paragraph(item.reference_answer, "暂无参考答案")
                + "\\par\\medskip\\hrule\\medskip\n"
            )
        return "\n".join(blocks) or "暂无可展示的面试问答记录。"

    @classmethod
    def _template(cls, report: InterviewReportResponse, generated_at: str) -> str:
        role = cls._tex(report.interview_role or "通用软件工程师")
        overview_row = (
            f"综合得分 & {cls._tex(report.overall_score)} & 评估覆盖 & {cls._tex(report.total_answers)} 条 \\\\\\"
            if report.overall_score is not None
            else f"评估覆盖 & {cls._tex(report.total_answers)} 条 & & \\\\\\"
        )
        return rf"""\documentclass[UTF8,a4paper,10.5pt]{{ctexart}}
\usepackage[margin=16mm,headheight=14pt]{{geometry}}
\usepackage{{fontspec}}
\usepackage{{xeCJK}}
\setmainfont{{Noto Serif CJK SC}}
\setCJKmainfont{{Noto Serif CJK SC}}
\setsansfont{{Noto Sans CJK SC}}
\setCJKsansfont{{Noto Sans CJK SC}}
\usepackage{{xcolor}}
\usepackage{{array,tabularx,enumitem,longtable,booktabs,fancyhdr,hyperref,titlesec,fvextra}}
\definecolor{{ink}}{{HTML}}{{172033}}
\definecolor{{muted}}{{HTML}}{{5B6678}}
\definecolor{{accent}}{{HTML}}{{8B1E3F}}
\definecolor{{line}}{{HTML}}{{D9DEE7}}
\hypersetup{{hidelinks}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\small\color{{muted}}面面通 · 面试评估报告}}
\fancyhead[R]{{\small\color{{muted}}{role}}}
\fancyfoot[C]{{\small\color{{muted}}\thepage}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{4pt}}
\renewcommand{{\arraystretch}}{{1.35}}
\setlist[itemize]{{leftmargin=1.4em,itemsep=2pt,topsep=3pt,parsep=0pt}}
\titleformat{{\section}}{{\Large\bfseries\color{{ink}}}}{{}}{{0pt}}{{}}[\vspace{{2pt}}\color{{accent}}\titlerule]
\titlespacing*{{\section}}{{0pt}}{{16pt}}{{8pt}}
\titleformat{{\subsection}}{{\normalsize\bfseries\color{{ink}}}}{{}}{{0pt}}{{}}
\titlespacing*{{\subsection}}{{0pt}}{{10pt}}{{4pt}}
\newcommand{{\reportlabel}}[1]{{\textcolor{{muted}}{{\small #1}}}}
\newcommand{{\reportvalue}}[1]{{\textcolor{{ink}}{{\bfseries #1}}}}
\begin{{document}}

{{\color{{accent}}\rule{{5pt}}{{38pt}}\hspace{{9pt}}\begin{{minipage}}[t]{{0.88\textwidth}}
{{\Huge\bfseries\color{{ink}} {role}}}\\[3pt]
{{\large\color{{accent}}面试评估报告}}
\end{{minipage}}}}

\vspace{{4pt}}
\begin{{tabularx}}{{\textwidth}}{{>{{\reportlabel}}l X >{{\reportlabel}}l X}}
面试级别 & {{\reportvalue{{{cls._tex(report.interview_level or '未设置')}}}}} & 面试类型 & {{\reportvalue{{{cls._tex(report.interview_type or '未设置')}}}}} \\
目标公司 & {{\reportvalue{{{cls._tex(report.target_company or '未设置')}}}}} & 有效作答 & {{\reportvalue{{{cls._tex(report.total_answers)}}}}} \\
导出时间 & {{\reportvalue{{{cls._tex(generated_at)}}}}} & 评估版本 & {{\reportvalue{{{cls._tex(report.assessment_version)}}}}} \\
\end{{tabularx}}

\section*{{面试评价}}
\begin{{tabularx}}{{\textwidth}}{{>{{\reportlabel}}l >{{\reportvalue}}r >{{\reportlabel}}l >{{\reportvalue}}r}}
{overview_row}
{cls._score_rows(report)}
\end{{tabularx}}

\section*{{综合总结}}
{cls._paragraph(report.summary)}

\section*{{内容分析}}
{cls._paragraph(report.content_analysis)}

\begin{{minipage}}[t]{{0.48\textwidth}}
\section*{{优势亮点}}
\begin{{itemize}}
{cls._items(report.strengths, '暂无明显优势项')}
\end{{itemize}}
\end{{minipage}}\hfill
\begin{{minipage}}[t]{{0.48\textwidth}}
\section*{{待提升项}}
\begin{{itemize}}
{cls._items(report.improvement_areas, '暂无明显短板')}
\end{{itemize}}
\end{{minipage}}

\section*{{后续建议}}
\begin{{itemize}}
{cls._items(report.recommendations, '暂无建议')}
\end{{itemize}}

\section*{{能力覆盖与置信度}}
\reportlabel{{{cls._tex(report.coverage_status)}}}
\begin{{longtable}}{{p{{0.22\textwidth}}p{{0.10\textwidth}}p{{0.20\textwidth}}p{{0.40\textwidth}}}}
\toprule
能力 & 分数 & 覆盖情况 & 证据 \\
\midrule
\endhead
{cls._competency_rows(report)}
\bottomrule
\end{{longtable}}

\section*{{面试问答记录}}
{cls._question_blocks(report)}

\vfill
\begin{{center}}
\small\color{{muted}}本报告基于本场有效作答生成；能力维度缺少有效数据时不显示，不以 0 代替。
\end{{center}}
\end{{document}}
"""

    @staticmethod
    def _check_xelatex() -> str:
        executable = shutil.which("xelatex")
        if not executable:
            raise InterviewReportPdfError("服务器未安装 XeLaTeX，暂时无法生成报告 PDF。")
        return executable

    def build(self, report: InterviewReportResponse, generated_at: str) -> bytes:
        executable = self._check_xelatex()
        with tempfile.TemporaryDirectory(prefix="mianmiantong-report-") as temp_dir:
            workdir = Path(temp_dir)
            tex_file = workdir / "report.tex"
            tex_file.write_text(self._template(report, generated_at), encoding="utf-8")
            result = subprocess.run(
                [
                    executable,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-file-line-error",
                    "-output-directory",
                    str(workdir),
                    str(tex_file),
                ],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            pdf_file = workdir / "report.pdf"
            if result.returncode != 0 or not pdf_file.exists():
                diagnostic = (result.stdout + "\n" + result.stderr)[-2000:]
                raise InterviewReportPdfError(f"XeLaTeX 编译失败：{diagnostic}")
            return pdf_file.read_bytes()
