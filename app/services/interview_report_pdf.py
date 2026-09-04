from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.schemas.chat import InterviewReportResponse


class InterviewReportPdfError(RuntimeError):
    """Raised when the server cannot compile the interview report PDF."""


class InterviewReportPdfBuilder:
    """Render a stable, selectable-text report with an available server renderer."""

    _score_fields = (
        ("technical_accuracy", "技术准确性"),
        ("knowledge_depth", "知识深度"),
        ("communication_clarity", "表达清晰度"),
        ("logical_structure", "逻辑结构"),
        ("problem_solving", "问题解决能力"),
        ("job_match_score", "岗位匹配度"),
    )

    _chromium_candidates = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    )

    @staticmethod
    def _html(value: object) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    @classmethod
    def _html_text(cls, value: object, fallback: str = "暂无内容。") -> str:
        text = str(value or "").strip() or fallback
        return cls._html(text).replace("\n", "<br>")

    @classmethod
    def _html_items(cls, values: list[str] | None, fallback: str) -> str:
        items = [str(item).strip() for item in (values or []) if str(item).strip()]
        return "".join(f"<li>{cls._html(item)}</li>" for item in (items or [fallback]))

    @classmethod
    def _html_score_cards(cls, report: InterviewReportResponse) -> str:
        cards = []
        for field, label in cls._score_fields:
            value = getattr(report, field, None)
            if value is not None:
                cards.append(
                    f'<div class="score"><span>{cls._html(label)}</span><strong>{cls._html(value)}</strong></div>'
                )
        return "".join(cards)

    @classmethod
    def _html_competencies(cls, report: InterviewReportResponse) -> str:
        rows = []
        for item in report.competency_assessments:
            evidence = item.evidence[0] if item.evidence else "尚缺少独立材料"
            rows.append(
                "<tr>"
                f"<td><strong>{cls._html(item.capability)}</strong></td>"
                f"<td>{cls._html(item.score)}</td>"
                f"<td>{cls._html(item.covered_questions)} 题 / {cls._html(item.confidence)}置信度</td>"
                f"<td>{cls._html(evidence[:180])}</td>"
                "</tr>"
            )
        return "".join(rows) or '<tr><td colspan="4">暂无有效能力覆盖数据。</td></tr>'

    @classmethod
    def _html_questions(cls, report: InterviewReportResponse) -> str:
        blocks = []
        for index, item in enumerate(report.interview_questions, start=1):
            evaluation = item.evaluation
            if item.evaluation_status in {"queued", "processing"}:
                score = "评估中"
                summary = "本题仍在评估，请稍后重新导出报告。"
            elif item.evaluation_status == "failed":
                score = "失败"
                summary = item.evaluation_error or "评估服务暂时不可用。"
            elif evaluation:
                score = f"{evaluation.overall_score} 分"
                summary = evaluation.summary or "暂无评估摘要。"
            else:
                score = "暂无"
                summary = "暂无评估结果。"

            consistency = ""
            if evaluation and evaluation.question_type == "项目深挖题":
                consistency = (
                    '<div class="consistency"><strong>经历一致性：'
                    f"{cls._html(evaluation.resume_consistency or '证据不足')}</strong> "
                    f"{cls._html(evaluation.consistency_summary or '')}</div>"
                )
            improvement = ""
            if evaluation and evaluation.correction_suggestion:
                improvement = (
                    '<div class="improvement"><strong>改进建议：</strong>'
                    f"{cls._html(evaluation.correction_suggestion)}</div>"
                )
            grounding = ""
            if item.question_evidence_items:
                anchors = "；".join(
                    f"{evidence.document_title or '技术文档'} / {evidence.section or '未标注章节'} / {evidence.evidence_id}"
                    for evidence in item.question_evidence_items[:3]
                )
                grounding = (
                    '<div class="grounding"><strong>本题项目深挖依据：</strong>'
                    f"{cls._html(anchors)}</div>"
                )
            answer = str(item.candidate_answer or "未记录回答").strip()
            if len(answer) > 700:
                answer = f"{answer[:700].rstrip()}..."
            blocks.append(
                '<article class="question">'
                f'<div class="question-head"><span>第 {index} 题</span><b>{cls._html(score)}</b></div>'
                f'<h3>{cls._html_text(item.question, "未记录问题")}</h3>'
                '<div class="label">候选人回答</div>'
                f'<div class="answer">{cls._html_text(answer, "未记录回答")}</div>'
                f"{grounding}"
                '<div class="label">评估结论</div>'
                f'<div class="summary">{cls._html_text(summary)}</div>'
                f"{consistency}{improvement}"
                "</article>"
            )
        return "".join(blocks) or '<p class="muted">暂无可展示的面试问答记录。</p>'

    @classmethod
    def _html_template(cls, report: InterviewReportResponse, generated_at: str) -> str:
        role = cls._html(report.interview_role or "通用软件工程师")
        overall = "待形成" if report.overall_score is None else cls._html(report.overall_score)
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{role} - 面试评估报告</title>
<style>
@page {{ size: A4; margin: 15mm 14mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #172033; font: 10.5pt/1.62 "Noto Sans CJK SC", "Droid Sans Fallback", sans-serif; }}
h1, h2, h3, p {{ margin: 0; }}
h1 {{ font-size: 25pt; line-height: 1.2; }}
h2 {{ margin: 22px 0 10px; padding-bottom: 5px; border-bottom: 2px solid #0e7490; font-size: 16pt; }}
h3 {{ margin: 6px 0 10px; font-size: 11.5pt; line-height: 1.55; }}
.hero {{ border-left: 6px solid #0e7490; padding: 4px 0 4px 13px; }}
.hero p {{ color: #0e7490; font-weight: 700; }}
.meta {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 15px; }}
.meta div, .score {{ border: 1px solid #d9e2ec; border-radius: 7px; padding: 8px 10px; }}
.meta span, .score span, .label, .muted {{ color: #64748b; font-size: 9pt; }}
.meta strong, .score strong {{ display: block; margin-top: 2px; }}
.overall {{ display: flex; align-items: center; gap: 18px; margin-top: 14px; padding: 13px; background: #eef8fa; border-radius: 9px; }}
.overall strong {{ color: #0e7490; font-size: 24pt; white-space: nowrap; }}
.scores {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }}
.score {{ display: flex; align-items: center; justify-content: space-between; }}
.score strong {{ color: #0e7490; font-size: 14pt; }}
.columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
.panel {{ padding: 12px 14px; background: #f8fafc; border-radius: 8px; break-inside: avoid; }}
ul {{ margin: 5px 0 0; padding-left: 18px; }}
li {{ margin: 3px 0; }}
table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
th {{ color: #475569; background: #f1f5f9; text-align: left; }}
th, td {{ padding: 7px 8px; border-bottom: 1px solid #d9e2ec; vertical-align: top; }}
.question {{ margin: 0 0 12px; padding: 12px 14px; border: 1px solid #d9e2ec; border-radius: 9px; break-inside: avoid; }}
.question-head {{ display: flex; justify-content: space-between; color: #0e7490; font-weight: 700; }}
.answer, .summary {{ margin: 3px 0 9px; overflow-wrap: anywhere; }}
.consistency, .improvement, .grounding {{ margin-top: 8px; padding: 7px 9px; border-radius: 6px; background: #fff8e8; }}
.grounding {{ background: #f0f9ff; }}
.improvement {{ background: #f1f5f9; }}
footer {{ margin-top: 18px; color: #64748b; font-size: 8.5pt; text-align: center; }}
</style>
</head>
<body>
<header class="hero"><h1>{role}</h1><p>面试评估报告</p></header>
<section class="meta">
  <div><span>面试级别</span><strong>{cls._html(report.interview_level or '未设置')}</strong></div>
  <div><span>面试类型</span><strong>{cls._html(report.interview_type or '未设置')}</strong></div>
  <div><span>目标公司</span><strong>{cls._html(report.target_company or '未设置')}</strong></div>
  <div><span>有效作答</span><strong>{cls._html(report.total_answers)} 题</strong></div>
</section>
<section class="overall"><strong>{overall} 分</strong><div><b>综合结论</b><br>{cls._html_text(report.summary)}</div></section>
<section class="scores">{cls._html_score_cards(report)}</section>
<h2>关键反馈</h2>
<section class="columns">
  <div class="panel"><b>优势亮点</b><ul>{cls._html_items(report.strengths, '暂无明显优势项')}</ul></div>
  <div class="panel"><b>优先改进</b><ul>{cls._html_items(report.improvement_areas, '暂无明显短板')}</ul></div>
</section>
<div class="panel" style="margin-top: 12px"><b>行动建议</b><ul>{cls._html_items(report.recommendations, '暂无建议')}</ul></div>
<h2>能力覆盖</h2>
<p class="muted">{cls._html(report.coverage_status)}</p>
<table><thead><tr><th>能力</th><th>分数</th><th>覆盖</th><th>关键依据</th></tr></thead><tbody>{cls._html_competencies(report)}</tbody></table>
<h2>逐题评估</h2>
{cls._html_questions(report)}
<footer>导出时间：{cls._html(generated_at)} · 评估版本：{cls._html(report.assessment_version)} · 详细证据与 Rubric 请在在线报告中查看</footer>
</body>
</html>"""

    @staticmethod
    def _tex(value: object) -> str:
        text = "" if value is None else str(value)
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

    @classmethod
    def _find_chromium(cls) -> str | None:
        for candidate in cls._chromium_candidates:
            executable = shutil.which(candidate)
            if executable:
                return executable
        return None

    @classmethod
    def _build_with_chromium(
        cls,
        executable: str,
        report: InterviewReportResponse,
        generated_at: str,
        workdir: Path,
    ) -> bytes:
        html_file = workdir / "report.html"
        pdf_file = workdir / "report.pdf"
        html_file.write_text(cls._html_template(report, generated_at), encoding="utf-8")
        try:
            result = subprocess.run(
                [
                    executable,
                    "--headless",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_file}",
                    html_file.resolve().as_uri(),
                ],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InterviewReportPdfError(f"Chrome PDF 渲染器不可用：{exc}") from exc
        if result.returncode != 0 or not pdf_file.exists():
            diagnostic = (result.stdout + "\n" + result.stderr)[-2000:]
            raise InterviewReportPdfError(f"Chrome PDF 渲染失败：{diagnostic}")
        return pdf_file.read_bytes()

    @classmethod
    def _build_with_xelatex(
        cls,
        executable: str,
        report: InterviewReportResponse,
        generated_at: str,
        workdir: Path,
    ) -> bytes:
        tex_file = workdir / "report.tex"
        tex_file.write_text(cls._template(report, generated_at), encoding="utf-8")
        try:
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
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InterviewReportPdfError(f"XeLaTeX 渲染器不可用：{exc}") from exc
        pdf_file = workdir / "report.pdf"
        if result.returncode != 0 or not pdf_file.exists():
            diagnostic = (result.stdout + "\n" + result.stderr)[-2000:]
            raise InterviewReportPdfError(f"XeLaTeX 编译失败：{diagnostic}")
        return pdf_file.read_bytes()

    def build(self, report: InterviewReportResponse, generated_at: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="mianmiantong-report-") as temp_dir:
            workdir = Path(temp_dir)
            renderer_errors = []
            chromium = self._find_chromium()
            if chromium:
                try:
                    return self._build_with_chromium(chromium, report, generated_at, workdir)
                except InterviewReportPdfError as exc:
                    renderer_errors.append(str(exc))

            xelatex = shutil.which("xelatex")
            if xelatex:
                try:
                    return self._build_with_xelatex(xelatex, report, generated_at, workdir)
                except InterviewReportPdfError as exc:
                    renderer_errors.append(str(exc))

            if renderer_errors:
                raise InterviewReportPdfError("；".join(renderer_errors))

            raise InterviewReportPdfError(
                "服务器未安装 Chrome/Chromium 或 XeLaTeX，暂时无法生成报告 PDF。"
            )
